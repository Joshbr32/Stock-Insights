import json, math
from typing import Any, Dict, Optional, List
from PySide6.QtCore import Qt, QSettings, QTimer, QThread
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QTableWidgetItem,
    QFrame, QMessageBox, QProgressBar, QTabWidget, QGroupBox, QSplitter,
    QInputDialog, QAbstractItemView, QComboBox, QDialog, QTableWidget,
    QDialogButtonBox, QHeaderView
)

import pandas as pd

from .theme import ThemeManager
from .widgets import MplCanvas, SpinnerLabel, WatchTable
from .workers import MarksWorker, SnapshotWorker, NetCheckWorker
from .data import human_money
from .cache import save_snapshot, get_cached_snapshot
from .logging_utils import setup_logging, serial_debug
from .portfolio_tab import PortfolioTab


class UserAccountDialog(QDialog):
    """Simple user-account editor for future SQL/auth + multi-account support."""

    def __init__(self, parent=None, settings: Optional[QSettings] = None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("User Account")
        self.resize(520, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form_group = QGroupBox("User")
        form_layout = QGridLayout(form_group)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Username")

        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self.account_combo = QComboBox()

        form_layout.addWidget(QLabel("Username"), 0, 0)
        form_layout.addWidget(self.username_edit, 0, 1)
        form_layout.addWidget(QLabel("Password"), 1, 0)
        form_layout.addWidget(self.password_edit, 1, 1)
        form_layout.addWidget(QLabel("Account"), 2, 0)
        form_layout.addWidget(self.account_combo, 2, 1)

        root.addWidget(form_group)

        accounts_group = QGroupBox("Accounts")
        accounts_layout = QVBoxLayout(accounts_group)

        self.accounts_table = QTableWidget(0, 1)
        self.accounts_table.setHorizontalHeaderLabels(["Account Name"])
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.setAlternatingRowColors(True)
        self.accounts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.accounts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.accounts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        accounts_layout.addWidget(self.accounts_table)

        account_btns = QHBoxLayout()
        self.add_account_btn = QPushButton("+ Add Account")
        self.remove_account_btn = QPushButton("– Remove Account")
        account_btns.addWidget(self.add_account_btn)
        account_btns.addWidget(self.remove_account_btn)
        account_btns.addStretch(1)
        accounts_layout.addLayout(account_btns)

        root.addWidget(accounts_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_and_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.add_account_btn.clicked.connect(self._add_account)
        self.remove_account_btn.clicked.connect(self._remove_selected_account)
        self.accounts_table.itemSelectionChanged.connect(self._sync_combo_to_selection)
        self.account_combo.currentTextChanged.connect(self._sync_selection_to_combo)

        self._load()

    def _load(self):
        s = self._settings
        username = ""
        password = ""
        accounts = ["Default"]
        active_account = "Default"

        if s is not None:
            username = str(s.value("user_account/username", "") or "")
            password = str(s.value("user_account/password", "") or "")
            raw_accounts = s.value("user_account/accounts", ["Default"])
            if isinstance(raw_accounts, str):
                try:
                    raw_accounts = json.loads(raw_accounts)
                except Exception:
                    raw_accounts = [x.strip() for x in raw_accounts.split(",") if x.strip()]
            if isinstance(raw_accounts, list):
                cleaned = []
                seen = set()
                for item in raw_accounts:
                    text = str(item or "").strip()
                    if text and text not in seen:
                        seen.add(text)
                        cleaned.append(text)
                if cleaned:
                    accounts = cleaned
            active_account = str(s.value("user_account/active_account", accounts[0]) or accounts[0])

        self.username_edit.setText(username)
        self.password_edit.setText(password)
        self._set_accounts(accounts, active_account)

    def _set_accounts(self, accounts: List[str], active_account: Optional[str] = None):
        cleaned = []
        seen = set()
        for account in accounts:
            text = str(account or "").strip()
            if text and text not in seen:
                seen.add(text)
                cleaned.append(text)
        if not cleaned:
            cleaned = ["Default"]

        self.accounts_table.setRowCount(0)
        for account in cleaned:
            row = self.accounts_table.rowCount()
            self.accounts_table.insertRow(row)
            item = QTableWidgetItem(account)
            self.accounts_table.setItem(row, 0, item)

        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItems(cleaned)
        target = active_account if active_account in cleaned else cleaned[0]
        self.account_combo.setCurrentText(target)
        self.account_combo.blockSignals(False)

        self._select_account_in_table(target)

    def _account_names(self) -> List[str]:
        out = []
        for row in range(self.accounts_table.rowCount()):
            item = self.accounts_table.item(row, 0)
            text = item.text().strip() if item else ""
            if text:
                out.append(text)
        return out

    def _select_account_in_table(self, account_name: str):
        for row in range(self.accounts_table.rowCount()):
            item = self.accounts_table.item(row, 0)
            if item and item.text().strip() == account_name:
                self.accounts_table.selectRow(row)
                return

    def _sync_combo_to_selection(self):
        row = self.accounts_table.currentRow()
        item = self.accounts_table.item(row, 0) if row >= 0 else None
        if item is None:
            return
        text = item.text().strip()
        if text and self.account_combo.currentText() != text:
            self.account_combo.blockSignals(True)
            self.account_combo.setCurrentText(text)
            self.account_combo.blockSignals(False)

    def _sync_selection_to_combo(self, text: str):
        if text:
            self._select_account_in_table(text)

    def _add_account(self):
        text, ok = QInputDialog.getText(self, "Add Account", "Account name:")
        if not ok:
            return
        account = str(text or "").strip()
        if not account:
            return
        existing = {name.lower(): name for name in self._account_names()}
        if account.lower() in existing:
            QMessageBox.information(self, "Duplicate account", f"{existing[account.lower()]} already exists.")
            self.account_combo.setCurrentText(existing[account.lower()])
            return
        names = self._account_names() + [account]
        self._set_accounts(names, active_account=account)

    def _remove_selected_account(self):
        names = self._account_names()
        if len(names) <= 1:
            QMessageBox.information(self, "Cannot remove", "At least one account must remain.")
            return
        current = self.account_combo.currentText().strip()
        if not current:
            return
        if QMessageBox.question(self, "Remove Account", f"Remove account '{current}'?") != QMessageBox.StandardButton.Yes:
            return
        names = [name for name in names if name != current]
        next_active = names[0] if names else "Default"
        self._set_accounts(names, active_account=next_active)

    def _accept_and_save(self):
        if self._settings is not None:
            accounts = self._account_names()
            active = self.account_combo.currentText().strip() or (accounts[0] if accounts else "Default")
            self._settings.setValue("user_account/username", self.username_edit.text().strip())
            self._settings.setValue("user_account/password", self.password_edit.text())
            self._settings.setValue("user_account/accounts", json.dumps(accounts))
            self._settings.setValue("user_account/active_account", active)
            self._settings.sync()
        self.accept()


class MainWindow(QMainWindow):
    ORG = "StockInsights"
    APP = "StocksGUI"

    SORT_DEFAULT = "Default (custom)"
    SORT_ALPHA = "Alphabetical"
    SORT_INDUSTRY = "Industry"
    SORT_PRICE = "Price"

    # Defaults (ms)
    L1_INTERVAL = 20_000
    L2_INTERVAL = 5 * 60_000
    NET_INTERVAL = 10_000

    L1_ENABLED = True
    L2_ENABLED = True

    SIM_COMM_BUY_DEFAULT = 9.99
    SIM_COMM_SELL_DEFAULT = 9.99

    def __init__(self):
        super().__init__()
        setup_logging()
        serial_debug("MainWindow init start")

        self.setWindowTitle("Stock Insights — Modular")
        self.resize(1320, 840)
        self._last_sidebar_size = 240
        self._busy_ops = 0
        self._online = True
        self.snapshot: Optional[Dict[str, Any]] = None

        self._build_ui()
        self.theme = ThemeManager(self)
        self.theme.apply()
        self.theme.start_watching()
        self._load_settings()
        self._bind_shortcuts()
        self._init_timers()
        serial_debug("MainWindow init done")

    # ------- Settings helpers -------
    def _settings(self) -> QSettings:
        return QSettings(self.ORG, self.APP)

    def _get_saved_watch_items(self) -> List[str]:
        s = self._settings()
        items = s.value("watchlist/items", [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = [x.strip() for x in items.split(",") if x.strip()]
        return [str(t).upper() for t in items] if items else []

    def _reload_custom_order(self):
        items = self._get_saved_watch_items() or ["NVDA", "SRPT", "RDDT", "FIG", "NCLH", "CCL"]
        self.watch.setRowCount(0)
        for sym in items:
            self._add_watch_row(sym)

    def _load_settings(self):
        s = self._settings()
        self._reload_custom_order()

        self.L1_INTERVAL = int(s.value("intervals/L1_INTERVAL", self.L1_INTERVAL))
        self.L2_INTERVAL = int(s.value("intervals/L2_INTERVAL", self.L2_INTERVAL))
        self.NET_INTERVAL = int(s.value("intervals/NET_INTERVAL", self.NET_INTERVAL))
        self.L1_ENABLED = bool(s.value("intervals/L1_ENABLED", True, type=bool))
        self.L2_ENABLED = bool(s.value("intervals/L2_ENABLED", True, type=bool))

        theme_override = s.value("ui/THEME_OVERRIDE", "System")
        self.theme.set_override_mode(theme_override)
        self.theme.set_match_system_accent(s.value("ui/MATCH_SYSTEM_ACCENT", True, type=bool))

        sidebar_visible = s.value("ui/sidebar_visible", True, type=bool)
        sizes = s.value("ui/splitter_sizes", [])
        if isinstance(sizes, str):
            try:
                sizes = json.loads(sizes)
            except Exception:
                sizes = []
        if sizes and isinstance(sizes, list) and len(sizes) == 2:
            try:
                sizes = [int(sizes[0]), int(sizes[1])]
                self.splitter.setSizes(sizes)
                self._last_sidebar_size = max(200, sizes[0])
            except Exception:
                pass
        self._set_sidebar_visible(sidebar_visible, apply_sizes=False)

    def _save_settings(self):
        s = self._settings()
        items: list[str] = [self.watch.item(r, 0).text() for r in range(self.watch.rowCount())]
        s.setValue("watchlist/items", items)
        sizes = self.splitter.sizes()
        s.setValue("ui/splitter_sizes", sizes)
        s.setValue("ui/sidebar_visible", self._is_sidebar_visible())
        s.setValue("intervals/L1_INTERVAL", self.L1_INTERVAL)
        s.setValue("intervals/L2_INTERVAL", self.L2_INTERVAL)
        s.setValue("intervals/NET_INTERVAL", self.NET_INTERVAL)
        s.setValue("intervals/L1_ENABLED", self.L1_ENABLED)
        s.setValue("intervals/L2_ENABLED", self.L2_ENABLED)
        s.setValue("ui/THEME_OVERRIDE", self.theme.override_mode)
        s.setValue("ui/MATCH_SYSTEM_ACCENT", self.theme.match_system_accent)
        s.sync()

    def _open_settings_dialog(self):
        from .settings_dialog import SettingsDialog

        cv = {
            "L1_INTERVAL": self.L1_INTERVAL,
            "L2_INTERVAL": self.L2_INTERVAL,
            "NET_INTERVAL": self.NET_INTERVAL,
            "L1_ENABLED": self.L1_ENABLED,
            "L2_ENABLED": self.L2_ENABLED,
            "THEME_OVERRIDE": self._settings().value(
                "ui/THEME_OVERRIDE", getattr(self.theme, "override_mode", "System")
            ),
            "MATCH_SYSTEM_ACCENT": self._settings().value(
                "ui/MATCH_SYSTEM_ACCENT", getattr(self.theme, "match_system_accent", True), type=bool
            ),
            "GOAL_PRESET_1": float(self._settings().value("goals/preset_1", 250000.0) or 250000.0),
            "GOAL_PRESET_2": float(self._settings().value("goals/preset_2", 500000.0) or 500000.0),
            "GOAL_PRESET_3": float(self._settings().value("goals/preset_3", 1000000.0) or 1000000.0),
            "TRADE_DEFAULT_QUANTITY": int(self._settings().value("trade_defaults/default_quantity", 1) or 1),
            "TRADE_QUANTITY_INCREMENT": int(self._settings().value("trade_defaults/quantity_increment", 1) or 1),
        }
        dlg = SettingsDialog(self, self._settings(), cv)
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            vals = dlg.get_values()
            self.L1_INTERVAL = int(vals["L1_INTERVAL"])
            self.L2_INTERVAL = int(vals["L2_INTERVAL"])
            self.NET_INTERVAL = int(vals["NET_INTERVAL"])
            self.L1_ENABLED = bool(vals["L1_ENABLED"])
            self.L2_ENABLED = bool(vals["L2_ENABLED"])

            self.theme.set_override_mode(vals["THEME_OVERRIDE"])
            self.theme.set_match_system_accent(vals["MATCH_SYSTEM_ACCENT"])
            s = self._settings()
            s.setValue("ui/THEME_OVERRIDE", self.theme.override_mode)
            s.setValue("ui/MATCH_SYSTEM_ACCENT", self.theme.match_system_accent)
            s.setValue("goals/preset_1", float(vals["GOAL_PRESET_1"]))
            s.setValue("goals/preset_2", float(vals["GOAL_PRESET_2"]))
            s.setValue("goals/preset_3", float(vals["GOAL_PRESET_3"]))
            s.setValue("trade_defaults/default_quantity", int(vals["TRADE_DEFAULT_QUANTITY"]))
            s.setValue("trade_defaults/quantity_increment", int(vals["TRADE_QUANTITY_INCREMENT"]))
            s.sync()

            self.timer_l1.setInterval(self.L1_INTERVAL)
            self.timer_l2.setInterval(self.L2_INTERVAL)
            self.timer_net.setInterval(self.NET_INTERVAL)
            (self.timer_l1.start() if self.L1_ENABLED else self.timer_l1.stop())
            (self.timer_l2.start() if self.L2_ENABLED else self.timer_l2.stop())

            self._save_settings()
            if hasattr(self, "portfolio_tab"):
                self.portfolio_tab.reload_goal_presets()

    def _open_user_account_dialog(self):
        dlg = UserAccountDialog(self, self._settings())
        dlg.exec()

    # ------- UI -------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.spinner = SpinnerLabel()
        self.lbl_updating = QLabel("")
        self.lbl_status = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(120)
        self.progress.setVisible(False)

        # Menus
        file_menu = self.menuBar().addMenu("&File")
        act_settings = file_menu.addAction("Settings…")
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._open_settings_dialog)

        act_user_account = file_menu.addAction("User Account…")
        act_user_account.triggered.connect(self._open_user_account_dialog)

        file_menu.addSeparator()
        file_menu.addAction("Quit").triggered.connect(self.close)

        view_menu = self.menuBar().addMenu("&View")
        self.act_toggle_sidebar = view_menu.addAction("Toggle Sidebar")
        self.act_toggle_sidebar.setCheckable(True)
        self.act_toggle_sidebar.setShortcut(QKeySequence("Ctrl+B"))
        self.act_toggle_sidebar.triggered.connect(self._toggle_sidebar)

        act_trade_history_columns = view_menu.addAction("Trade History Columns…")
        act_trade_history_columns.triggered.connect(
            lambda: getattr(self.portfolio_tab, "open_trade_history_view_settings", lambda: None)()
        )

        status_corner = QWidget(self)
        status_row = QHBoxLayout(status_corner)
        status_row.setContentsMargins(8, 0, 8, 0)
        status_row.setSpacing(8)
        status_row.addWidget(self.spinner)
        status_row.addWidget(self.lbl_updating)
        status_row.addWidget(self.lbl_status)
        status_row.addWidget(self.progress)
        self.menuBar().setCornerWidget(status_corner, Qt.Corner.TopRightCorner)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter)

        # Left: Watchlist
        left_wrap = QFrame()
        left_wrap.setObjectName("leftPane")
        left_layout = QVBoxLayout(left_wrap)
        title_row = QHBoxLayout()
        title = QLabel("Watchlist")
        title.setObjectName("leftTitle")
        self.sort_mode = QComboBox()
        self.sort_mode.addItems([self.SORT_DEFAULT, self.SORT_ALPHA, self.SORT_INDUSTRY, self.SORT_PRICE])
        self.sort_mode.currentTextChanged.connect(self._on_sort_mode_changed)
        self.sort_mode.setFixedWidth(170)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(QLabel("Sort:"))
        title_row.addWidget(self.sort_mode)
        left_layout.addLayout(title_row)

        self.watch = WatchTable(self)
        self.watch.itemDoubleClicked.connect(self._on_watch_double_clicked)
        left_layout.addWidget(self.watch, stretch=1)

        wl_btns = QHBoxLayout()
        self.add_btn = QPushButton("+ Add")
        self.add_btn.clicked.connect(self._on_add_ticker)
        self.remove_btn = QPushButton("– Remove")
        self.remove_btn.clicked.connect(self._on_remove_ticker)
        wl_btns.addWidget(self.add_btn)
        wl_btns.addWidget(self.remove_btn)
        left_layout.addLayout(wl_btns)
        self.splitter.addWidget(left_wrap)
        self.splitter.setStretchFactor(0, 0)

        # Right: Tabs
        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)

        # Portfolio tab
        self.portfolio_tab = PortfolioTab(self._settings(), self)
        self.tabs.addTab(self.portfolio_tab, "Portfolio")

        # Overview tab
        self.overview_tab = QWidget()
        ovl = QVBoxLayout(self.overview_tab)

        ticker_row = QHBoxLayout()
        self.ticker_edit = QLineEdit()
        self.ticker_edit.setPlaceholderText("Enter ticker (e.g., NVDA)")
        self.ticker_edit.setFixedWidth(220)
        self.ticker_edit.returnPressed.connect(self.on_fetch)
        self.fetch_btn = QPushButton("Fetch")
        self.fetch_btn.clicked.connect(self.on_fetch)
        ticker_row.addWidget(QLabel("Ticker:"))
        ticker_row.addWidget(self.ticker_edit)
        ticker_row.addWidget(self.fetch_btn)
        ticker_row.addStretch(1)
        ovl.addLayout(ticker_row)

        self.canvas = MplCanvas()
        chart_group = QGroupBox("Price — 1Y")
        chart_v = QVBoxLayout(chart_group)
        chart_v.addWidget(self.canvas)
        ovl.addWidget(chart_group)

        self.gen_group = QGroupBox("General")
        self.gen_grid = QGridLayout(self.gen_group)
        self._gen_labels: Dict[str, QLabel] = {}

        def add_gen_row(row, label_key, label_text):
            k = QLabel(label_text)
            v = QLabel("—")
            self._gen_labels[label_key] = v
            self.gen_grid.addWidget(k, row, 0)
            self.gen_grid.addWidget(v, row, 1)

        add_gen_row(0, "previous_close", "Previous Close")
        add_gen_row(1, "open", "Open")
        add_gen_row(2, "bid", "Bid")
        add_gen_row(3, "ask", "Ask")
        add_gen_row(4, "day_range", "Day's Range")
        add_gen_row(5, "fifty_two_week_range", "52 Week Range")
        add_gen_row(6, "volume", "Volume")
        add_gen_row(7, "avg_volume", "Avg. Volume")
        add_gen_row(8, "market_cap", "Market Cap")

        ovl.addWidget(self.gen_group)
        self.tabs.addTab(self.overview_tab, "Overview")

        # Statistics tab
        self.stats_tab = QWidget()
        stl = QVBoxLayout(self.stats_tab)
        self.table = self._mk_table()
        stl.addWidget(self.table)
        self.tabs.addTab(self.stats_tab, "Statistics")

        # Placeholder tabs
        self.fin_tab = QWidget()
        ft = QVBoxLayout(self.fin_tab)
        ft.addWidget(QLabel("Financials — coming soon"))
        self.tabs.addTab(self.fin_tab, "Financials")

        self.analysis_tab = QWidget()
        at = QVBoxLayout(self.analysis_tab)
        at.addWidget(QLabel("Analysis — coming soon"))
        self.tabs.addTab(self.analysis_tab, "Analysis")

        self.news_tab = QWidget()
        nt = QVBoxLayout(self.news_tab)
        nt.addWidget(QLabel("News — coming soon"))
        self.tabs.addTab(self.news_tab, "News")

        self.splitter.addWidget(right_wrap)
        self.splitter.setStretchFactor(1, 1)

        self.statusBar().showMessage("Ready")

    def _mk_table(self):
        t = QTableWidget(0, 2)
        t.setHorizontalHeaderLabels(["Metric", "Value"])
        t.horizontalHeader().setStretchLastSection(True)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(t.EditTrigger.NoEditTriggers)
        return t

    # ------- Timers / connectivity -------
    def _init_timers(self):
        serial_debug("Initializing timers (L1/L2/NET)")
        self.timer_l1 = QTimer(self)
        self.timer_l1.setInterval(self.L1_INTERVAL)
        self.timer_l1.timeout.connect(self._level1_tick)
        self.timer_l2 = QTimer(self)
        self.timer_l2.setInterval(self.L2_INTERVAL)
        self.timer_l2.timeout.connect(self._level2_tick)
        self.timer_net = QTimer(self)
        self.timer_net.setInterval(self.NET_INTERVAL)
        self.timer_net.timeout.connect(self._kick_netcheck)
        (self.timer_l1.start() if self.L1_ENABLED else self.timer_l1.stop())
        (self.timer_l2.start() if self.L2_ENABLED else self.timer_l2.stop())
        self.timer_net.start()
        self._kick_netcheck()
        self._level1_tick()

    def _kick_netcheck(self):
        serial_debug("Network check tick")
        w = NetCheckWorker()
        th = QThread(self)
        w.moveToThread(th)
        th.started.connect(w.run)
        w.done.connect(lambda ok: self._on_net_status(ok, th, w))
        th.finished.connect(th.deleteLater)
        th.start()

    def _on_net_status(self, ok: bool, thread: QThread, worker):
        serial_debug(f"Network status: {ok}")
        self._online = ok
        dot = "●"
        if ok:
            self.lbl_status.setText(f"{dot} Online")
            self.lbl_status.setStyleSheet("color: #22c55e;")
        else:
            self.lbl_status.setText(f"{dot} Offline")
            self.lbl_status.setStyleSheet("color: #ef4444;")
        thread.quit()

    # ------- Busy indicator -------
    def _busy_enter(self):
        self._busy_ops += 1
        if self._busy_ops == 1:
            self.spinner.start(90)
            self.lbl_updating.setText("Updating…")

    def _busy_leave(self):
        self._busy_ops = max(0, self._busy_ops - 1)
        if self._busy_ops == 0:
            self.spinner.stop()
            self.lbl_updating.setText("")

    # ------- Level 1: marks -------
    def _level1_tick(self):
        tickers = [self.watch.item(r, 0).text() for r in range(self.watch.rowCount())]
        if hasattr(self, "portfolio_tab"):
            tickers.extend(self.portfolio_tab.holdings_symbols())
        tickers = list(dict.fromkeys([t for t in tickers if t]))
        if not tickers:
            return
        self._busy_enter()
        w = MarksWorker(tickers)
        th = QThread(self)
        w.moveToThread(th)
        th.started.connect(w.run)
        w.done.connect(lambda data: self._on_marks(data, th, w))
        w.error.connect(lambda msg: self._on_marks_error(msg, th, w))
        th.finished.connect(th.deleteLater)
        th.start()

    def _on_marks(self, data: Dict[str, Dict[str, Optional[float]]], thread: QThread, worker):
        if hasattr(self, "portfolio_tab"):
            self.portfolio_tab.update_marks(data)
        for r in range(self.watch.rowCount()):
            sym = self.watch.item(r, 0).text()
            row = data.get(sym, {})
            cell = self.watch.item(r, 1)
            if cell is None:
                cell = QTableWidgetItem("—")
                self.watch.setItem(r, 1, cell)
            if "price" in row and row["price"] is not None:
                cell.setText(f"{row['price']:.2f}")
        if self.snapshot:
            sym = self.snapshot.get("ticker")
            row = data.get(sym, {})
            if row.get("bid") is not None:
                self._gen_labels["bid"].setText(f"{row['bid']:.2f}")
            if row.get("ask") is not None:
                self._gen_labels["ask"].setText(f"{row['ask']:.2f}")
        thread.quit()
        self._busy_leave()

    def _on_marks_error(self, msg: str, thread: QThread, worker):
        self.lbl_status.setText("● Offline")
        self.lbl_status.setStyleSheet("color: #ef4444;")
        thread.quit()
        self._busy_leave()

    # ------- Level 2: snapshot -------
    def _level2_tick(self):
        sym = self.ticker_edit.text().strip() or self._watch_current_symbol() or (
            self.watch.item(0, 0).text() if self.watch.rowCount() > 0 else None
        )
        if not sym:
            return
        self._fetch_snapshot_async(sym, level2=True)

    def _fetch_snapshot_async(self, ticker: str, level2: bool = False):
        serial_debug(f"_fetch_snapshot_async: {ticker}, level2={level2}")
        self._busy_enter()
        self.statusBar().showMessage(f"Refreshing {ticker}…")
        w = SnapshotWorker(ticker)
        th = QThread(self)
        w.moveToThread(th)
        th.started.connect(w.run)
        w.finished.connect(lambda snap: self._on_snapshot(snap, ticker, level2, th, w))
        w.error.connect(lambda e: self._on_snapshot_error(e, ticker, th, w))
        th.finished.connect(th.deleteLater)
        th.start()

    def _on_snapshot(self, snapshot: dict, ticker: str, level2: bool, thread: QThread, worker):
        serial_debug(f"_on_snapshot: {ticker}, level2={level2}")
        self.snapshot = snapshot
        save_snapshot(self.APP, ticker, snapshot)
        self._plot_chart(snapshot)
        self._populate_overview(snapshot)
        self._populate_table(snapshot)
        self.statusBar().showMessage(f"Done — {ticker}")
        thread.quit()
        self._busy_leave()

    def _on_snapshot_error(self, message: str, ticker: str, thread: QThread, worker):
        serial_debug(f"_on_snapshot_error: {ticker}, {message[:120]!r}")
        cached = get_cached_snapshot(self.APP, ticker)
        if cached:
            self.snapshot = cached
            self._plot_chart(self.snapshot)
            self._populate_overview(self.snapshot)
            self._populate_table(self.snapshot)
            self.statusBar().showMessage(f"Offline — showing cached {ticker}")
        else:
            self.statusBar().showMessage("Error")
            QMessageBox.critical(self, "Fetch error", f"Failed to fetch data:\n{message}")
        thread.quit()
        self._busy_leave()

    # ------- Actions / sorting -------
    def _bind_shortcuts(self):
        act_refresh = QAction("Refresh Now (F5)", self)
        act_refresh.setShortcut(QKeySequence("F5"))
        act_refresh.triggered.connect(self._refresh_now)
        self.addAction(act_refresh)

    def _refresh_now(self):
        self._level1_tick()
        self._level2_tick()

    def _is_sidebar_visible(self):
        return self.splitter.sizes()[0] > 0

    def _set_sidebar_visible(self, visible: bool, apply_sizes: bool = True):
        sizes = self.splitter.sizes()
        total = sum(sizes) if sizes else 1000
        right = max(1, total - (sizes[0] if sizes else 240))
        if visible:
            left = getattr(self, "_last_sidebar_size", 240) or 240
            if apply_sizes:
                self.splitter.setSizes([left, right])
            self.act_toggle_sidebar.setChecked(True)
        else:
            if sizes and sizes[0] > 0:
                self._last_sidebar_size = sizes[0]
            if apply_sizes:
                self.splitter.setSizes([0, total])
            self.act_toggle_sidebar.setChecked(False)

    def _toggle_sidebar(self):
        self._set_sidebar_visible(not self._is_sidebar_visible())

    def _add_watch_row(self, sym: str, mark: str = "—", industry: str = "—"):
        r = self.watch.rowCount()
        self.watch.insertRow(r)
        it0 = QTableWidgetItem(sym.upper())
        f = it0.font()
        f.setBold(True)
        it0.setFont(f)
        it0.setFlags(it0.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it1 = QTableWidgetItem(mark)
        it1.setFlags(it1.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it2 = QTableWidgetItem(industry)
        it2.setFlags(it2.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.watch.setItem(r, 0, it0)
        self.watch.setItem(r, 1, it1)
        self.watch.setItem(r, 2, it2)

    def _watch_current_row(self) -> int:
        return self.watch.currentRow()

    def _watch_current_symbol(self) -> Optional[str]:
        r = self._watch_current_row()
        return self.watch.item(r, 0).text() if r >= 0 else None

    def _on_add_ticker(self):
        text, ok = QInputDialog.getText(self, "Add ticker", "Symbol:")
        if not ok or not text.strip():
            return
        sym = text.strip().upper()
        if not all(ch.isalnum() or ch in ".-" for ch in sym):
            QMessageBox.warning(self, "Invalid symbol", "Use letters, numbers, dot or dash only.")
            return
        for r in range(self.watch.rowCount()):
            if self.watch.item(r, 0).text() == sym:
                self.watch.selectRow(r)
                self.ticker_edit.setText(sym)
                return
        self._add_watch_row(sym)
        self.watch.selectRow(self.watch.rowCount() - 1)
        self.ticker_edit.setText(sym)
        if self.sort_mode.currentText() == self.SORT_DEFAULT:
            self._save_settings()

    def _on_remove_ticker(self):
        r = self._watch_current_row()
        if r < 0:
            QMessageBox.information(self, "Select item", "Pick a ticker to remove.")
            return
        sym = self.watch.item(r, 0).text()
        if QMessageBox.question(self, "Remove", f"Remove {sym} from watchlist?") != QMessageBox.StandardButton.Yes:
            return
        self.watch.removeRow(r)
        if self.ticker_edit.text().strip().upper() == sym:
            self.ticker_edit.clear()
        if self.sort_mode.currentText() == self.SORT_DEFAULT:
            self._save_settings()

    def _on_watch_double_clicked(self, item):
        try:
            row = item.row()
            sym_item = self.watch.item(row, 0)
            if sym_item:
                sym = sym_item.text()
                self.ticker_edit.setText(sym)
                serial_debug(f"Double-click on {sym} -> on_fetch()")
                self.on_fetch()
        except Exception:
            pass

    def _ctx_fetch_selected(self):
        sym = self._watch_current_symbol()
        if not sym:
            return
        self.ticker_edit.setText(sym)
        self.on_fetch()

    def _ctx_rename_selected(self):
        r = self._watch_current_row()
        if r < 0:
            return
        old = self.watch.item(r, 0).text()
        text, ok = QInputDialog.getText(self, "Rename ticker", "Symbol:", text=old)
        if not ok or not text.strip():
            return
        sym = text.strip().upper()
        if not all(ch.isalnum() or ch in ".-" for ch in sym):
            QMessageBox.warning(self, "Invalid symbol", "Use letters, numbers, dot or dash only.")
            return
        for rr in range(self.watch.rowCount()):
            if rr != r and self.watch.item(rr, 0).text() == sym:
                QMessageBox.information(self, "Duplicate", f"{sym} is already in the list.")
                return
        self.watch.item(r, 0).setText(sym)
        if self.ticker_edit.text().strip().upper() == old:
            self.ticker_edit.setText(sym)

    def _ctx_move_row(self, delta: int):
        if self.sort_mode.currentText() != self.SORT_DEFAULT:
            QMessageBox.information(self, "Reorder disabled", "Switch to Default (custom) sort to reorder.")
            return
        r = self._watch_current_row()
        if r < 0:
            return
        new_r = r + delta
        if not (0 <= new_r < self.watch.rowCount()):
            return
        data = [self.watch.item(r, c).text() for c in range(3)]
        self.watch.removeRow(r)
        self.watch.insertRow(new_r)
        for c, text in enumerate(data):
            item = QTableWidgetItem(text)
            if c == 0:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.watch.setItem(new_r, c, item)
        self.watch.selectRow(new_r)
        self._save_settings()

    def _on_sort_mode_changed(self, mode: str):
        if mode == self.SORT_DEFAULT:
            self.watch.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.watch.setSortingEnabled(False)
            self._reload_custom_order()
        elif mode == self.SORT_ALPHA:
            self._apply_sort_by_column(0, True, False)
        elif mode == self.SORT_INDUSTRY:
            self._apply_sort_by_column(2, True, False)
        elif mode == self.SORT_PRICE:
            self._apply_sort_by_column(1, False, True)

    def _apply_sort_by_column(self, col: int, case_insensitive: bool, numeric: bool):
        self.watch.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.watch.setSortingEnabled(False)
        rows = []
        for r in range(self.watch.rowCount()):
            cells = [self.watch.item(r, c).text() if self.watch.item(r, c) else "" for c in range(3)]
            rows.append(cells)

        def key(row):
            v = row[col]
            if numeric:
                try:
                    return float(v.replace(",", "")) if v not in ("", "—") else float("-inf")
                except Exception:
                    return float("-inf")
            return v.lower() if case_insensitive else v

        rows.sort(key=key)
        self.watch.setRowCount(0)
        for sym, mark, ind in rows:
            self._add_watch_row(sym, mark, ind)
        if self.watch.rowCount() > 0:
            self.watch.selectRow(0)

    # ------- Public actions -------
    def on_fetch(self):
        ticker = self.ticker_edit.text().strip() or self._watch_current_symbol()
        if not ticker:
            QMessageBox.warning(self, "Input required", "Please enter or select a ticker (e.g., NVDA)")
            return
        self._fetch_snapshot_async(ticker, level2=False)

    # ------- UI population -------
    def _populate_overview(self, snap: Dict[str, Any]):
        o = snap.get("overview", {})
        t = snap["technicals"]

        def fnum(x, nd=2):
            return f"{x:.{nd}f}" if isinstance(x, (int, float)) and not math.isnan(x) else "—"

        def num(x):
            return human_money(x) if isinstance(x, (int, float)) else "—"

        day_rng = f"{fnum(o.get('day_low'))} – {fnum(o.get('day_high'))}" if (o.get("day_low") is not None or o.get("day_high") is not None) else "—"
        wk52_rng = f"{fnum(t.get('fifty_two_week_low'))} – {fnum(t.get('fifty_two_week_high'))}" if (t.get("fifty_two_week_low") is not None or t.get("fifty_two_week_high") is not None) else "—"
        setv = self._gen_labels
        setv["previous_close"].setText(fnum(o.get("previous_close")))
        setv["open"].setText(fnum(o.get("open")))
        setv["bid"].setText(fnum(o.get("bid")))
        setv["ask"].setText(fnum(o.get("ask")))
        setv["day_range"].setText(day_rng)
        setv["fifty_two_week_range"].setText(wk52_rng)
        setv["volume"].setText(num(o.get("volume")))
        setv["avg_volume"].setText(num(o.get("avg_volume")))
        setv["market_cap"].setText(num(o.get("market_cap")))

    def _populate_table(self, snap: Dict[str, Any]):
        rows = []
        c = snap["company"]
        q = snap["quote"]
        f = snap["financials"]
        t = snap["technicals"]

        def pct(x):
            return f"{x:.2f}%" if isinstance(x, (int, float)) and not math.isnan(x) else "—"

        def num(x):
            return human_money(x) if isinstance(x, (int, float)) else "—"

        def fnum(x, nd=2):
            return f"{x:.{nd}f}" if isinstance(x, (int, float)) and not math.isnan(x) else "—"

        rows.extend([
            ("Name", c.get("name", "—")),
            ("Exchange", c.get("exchange", "—")),
            ("Currency", c.get("currency", "—")),
            ("Sector", c.get("sector", "—")),
            ("Industry", c.get("industry", "—")),
            ("Country", c.get("country", "—")),
            ("Website", c.get("website", "—")),
            ("—", "—"),
            ("Market Cap", num(q.get("market_cap"))),
            ("Enterprise Value", num(q.get("enterprise_value"))),
            ("Shares Outstanding", num(q.get("shares_outstanding"))),
            ("PE (TTM)", fnum(q.get("trailing_pe"))),
            ("Forward PE", fnum(q.get("forward_pe"))),
            ("P/B", fnum(q.get("price_to_book"))),
            ("P/S (TTM)", fnum(q.get("price_to_sales_ttm"))),
            ("Dividend Yield", pct((q.get("dividend_yield") or 0) * 100)),
            ("Payout Ratio", pct((q.get("payout_ratio") or 0) * 100)),
            ("Beta", fnum(q.get("beta"))),
            ("—", "—"),
            ("Revenue (TTM)", num(f.get("revenue_ttm"))),
            ("EBITDA", num(f.get("ebitda"))),
            ("Net Income", num(f.get("net_income"))),
            ("—", "—"),
            ("52w High", fnum(t.get("fifty_two_week_high"))),
            ("52w Low", fnum(t.get("fifty_two_week_low"))),
            ("SMA 50", fnum(t.get("sma_50"))),
            ("SMA 200", fnum(t.get("sma_200"))),
            ("Price vs SMA50", pct(t.get("price_vs_sma50_pct")) if t.get("price_vs_sma50_pct") is not None else "—"),
            ("Price vs SMA200", pct(t.get("price_vs_sma200_pct")) if t.get("price_vs_sma200_pct") is not None else "—"),
            ("RSI(14)", fnum(t.get("rsi_14"))),
            ("As of (UTC)", snap.get("as_of", "—")),
        ])
        self.table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(k))
            it = QTableWidgetItem(v)
            if k == "Website" and v not in ("—", None):
                it.setToolTip(v)
            self.table.setItem(i, 1, it)
        self.table.resizeColumnsToContents()

    def _plot_chart(self, snap: Dict[str, Any]):
        closes = snap.get("_history_close", [])
        self.canvas.ax.clear()
        if not closes or len(closes) < 10:
            self.canvas.ax.text(0.5, 0.5, "Not enough data to plot", ha="center", va="center", transform=self.canvas.ax.transAxes)
            self.canvas.draw()
            return
        series = pd.Series(closes)
        sma50 = series.rolling(50).mean() if len(series) >= 50 else None
        sma200 = series.rolling(200).mean() if len(series) >= 200 else None
        self.canvas.ax.plot(series.index, series.values, label="Price")
        if sma50 is not None and not sma50.isna().all():
            self.canvas.ax.plot(sma50.index, sma50.values, label="SMA 50")
        if sma200 is not None and not sma200.isna().all():
            self.canvas.ax.plot(sma200.index, sma200.values, label="SMA 200")
        self.canvas.ax.set_title(f"{snap['ticker']} — 1Y Price")
        self.canvas.ax.set_xlabel("Days")
        self.canvas.ax.set_ylabel("Price")
        self.canvas.ax.legend()
        self.canvas.draw()
