import json
from typing import Dict, List, Optional
from PySide6.QtCore import Qt, QSettings, QTimer, QThread
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QTableWidgetItem,
    QFrame, QMessageBox, QProgressBar, QTabWidget, QGroupBox, QSplitter,
    QInputDialog, QAbstractItemView, QComboBox, QDialog, QTableWidget,
    QDialogButtonBox, QHeaderView,
)

from .theme import ThemeManager
from .widgets import SpinnerLabel, WatchTable
from .workers import MarksWorker, NetCheckWorker
from .logging_utils import setup_logging, serial_debug
from .portfolio_tab import PortfolioTab


class UserAccountDialog(QDialog):
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
        form_layout.setContentsMargins(14, 18, 14, 14)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(10)

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
        form_layout.addWidget(QLabel("Active Account"), 2, 0)
        form_layout.addWidget(self.account_combo, 2, 1)
        root.addWidget(form_group)

        accounts_group = QGroupBox("Accounts")
        accounts_layout = QVBoxLayout(accounts_group)
        accounts_layout.setContentsMargins(14, 18, 14, 14)
        accounts_layout.setSpacing(10)

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
        self.remove_account_btn = QPushButton("- Remove Account")
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
        username = password = ""
        accounts = ["Default"]
        active_account = "Default"
        if s is not None:
            username = str(s.value("user_account/username", "") or "")
            password = str(s.value("user_account/password", "") or "")
            raw = s.value("user_account/accounts", ["Default"])
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = [x.strip() for x in raw.split(",") if x.strip()]
            if isinstance(raw, list):
                cleaned, seen = [], set()
                for item in raw:
                    t = str(item or "").strip()
                    if t and t not in seen:
                        seen.add(t); cleaned.append(t)
                if cleaned:
                    accounts = cleaned
            active_account = str(s.value("user_account/active_account", accounts[0]) or accounts[0])
        self.username_edit.setText(username)
        self.password_edit.setText(password)
        self._set_accounts(accounts, active_account)

    def _set_accounts(self, accounts: List[str], active_account: Optional[str] = None):
        cleaned, seen = [], set()
        for a in accounts:
            t = str(a or "").strip()
            if t and t not in seen:
                seen.add(t); cleaned.append(t)
        if not cleaned:
            cleaned = ["Default"]
        self.accounts_table.setRowCount(0)
        for a in cleaned:
            r = self.accounts_table.rowCount()
            self.accounts_table.insertRow(r)
            self.accounts_table.setItem(r, 0, QTableWidgetItem(a))
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItems(cleaned)
        target = active_account if active_account in cleaned else cleaned[0]
        self.account_combo.setCurrentText(target)
        self.account_combo.blockSignals(False)
        self._select_account_in_table(target)

    def _account_names(self) -> List[str]:
        out = []
        for r in range(self.accounts_table.rowCount()):
            item = self.accounts_table.item(r, 0)
            t = item.text().strip() if item else ""
            if t:
                out.append(t)
        return out

    def _select_account_in_table(self, name: str):
        for r in range(self.accounts_table.rowCount()):
            item = self.accounts_table.item(r, 0)
            if item and item.text().strip() == name:
                self.accounts_table.selectRow(r); return

    def _sync_combo_to_selection(self):
        r = self.accounts_table.currentRow()
        item = self.accounts_table.item(r, 0) if r >= 0 else None
        if item is None: return
        t = item.text().strip()
        if t and self.account_combo.currentText() != t:
            self.account_combo.blockSignals(True)
            self.account_combo.setCurrentText(t)
            self.account_combo.blockSignals(False)

    def _sync_selection_to_combo(self, text: str):
        if text: self._select_account_in_table(text)

    def _add_account(self):
        text, ok = QInputDialog.getText(self, "Add Account", "Account name:")
        if not ok: return
        account = str(text or "").strip()
        if not account: return
        existing = {n.lower(): n for n in self._account_names()}
        if account.lower() in existing:
            QMessageBox.information(self, "Duplicate account", f"{existing[account.lower()]} already exists.")
            self.account_combo.setCurrentText(existing[account.lower()]); return
        self._set_accounts(self._account_names() + [account], active_account=account)

    def _remove_selected_account(self):
        names = self._account_names()
        if len(names) <= 1:
            QMessageBox.information(self, "Cannot remove", "At least one account must remain."); return
        current = self.account_combo.currentText().strip()
        if not current: return
        if QMessageBox.question(self, "Remove Account", f"Remove account '{current}'?") != QMessageBox.StandardButton.Yes:
            return
        names = [n for n in names if n != current]
        self._set_accounts(names, active_account=names[0] if names else "Default")

    def _accept_and_save(self):
        if self._settings is not None:
            accounts = self._account_names()
            active = self.account_combo.currentText().strip() or (accounts[0] if accounts else "Default")
            self._settings.setValue("user_account/username", self.username_edit.text().strip())
            self._settings.setValue("user_account/password", self.password_edit.text())
            self._settings.setValue("user_account/accounts", json.dumps(accounts))
            self._settings.setValue("user_account/active_account", active)
            raw = self._settings.value("portfolio/goal_dashboard_accounts", [])
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = [x.strip() for x in raw.split(",") if x.strip()]
            if not isinstance(raw, list): raw = []
            sel = {str(n).strip() for n in raw if str(n).strip()} or set(accounts)
            sel.update(accounts)
            self._settings.setValue("portfolio/goal_dashboard_accounts", json.dumps([n for n in accounts if n in sel]))
            self._settings.sync()
        self.accept()


class MainWindow(QMainWindow):
    ORG = "StockInsights"
    APP = "StocksGUI"

    SORT_DEFAULT = "Default (custom)"
    SORT_ALPHA = "Alphabetical"
    SORT_INDUSTRY = "Industry"
    SORT_PRICE = "Price"

    L1_INTERVAL = 20_000
    NET_INTERVAL = 10_000
    L1_ENABLED = True

    def __init__(self):
        super().__init__()
        setup_logging()
        serial_debug("MainWindow init start")
        self.setWindowTitle("Stock Insights - Portfolio")
        self.resize(1200, 800)
        self._last_sidebar_size = 240
        self._busy_ops = 0
        self._online = True
        self._portfolio_tabs: Dict[str, PortfolioTab] = {}

        self._build_ui()
        self.theme = ThemeManager(self)
        self.theme.apply()
        self.theme.start_watching()
        self._load_settings()
        self._bind_shortcuts()
        self._init_timers()
        serial_debug("MainWindow init done")

    # ---- Settings ----

    def _settings(self) -> QSettings:
        return QSettings(self.ORG, self.APP)

    def _get_account_names(self) -> List[str]:
        s = self._settings()
        raw = s.value("user_account/accounts", ["Default"])
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except Exception: raw = [x.strip() for x in raw.split(",") if x.strip()]
        if not isinstance(raw, list) or not raw:
            return ["Default"]
        cleaned, seen = [], set()
        for item in raw:
            name = str(item or "").strip()
            if name and name not in seen:
                seen.add(name); cleaned.append(name)
        return cleaned or ["Default"]

    def _get_saved_watch_items(self) -> List[str]:
        s = self._settings()
        items = s.value("watchlist/items", [])
        if isinstance(items, str):
            try: items = json.loads(items)
            except Exception: items = [x.strip() for x in items.split(",") if x.strip()]
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
        self.NET_INTERVAL = int(s.value("intervals/NET_INTERVAL", self.NET_INTERVAL))
        self.L1_ENABLED = bool(s.value("intervals/L1_ENABLED", True, type=bool))
        self.theme.set_override_mode(s.value("ui/THEME_OVERRIDE", "System"))
        self.theme.set_match_system_accent(s.value("ui/MATCH_SYSTEM_ACCENT", True, type=bool))
        sidebar_visible = s.value("ui/sidebar_visible", True, type=bool)
        sizes = s.value("ui/splitter_sizes", [])
        if isinstance(sizes, str):
            try: sizes = json.loads(sizes)
            except Exception: sizes = []
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
        s.setValue("watchlist/items", [self.watch.item(r, 0).text() for r in range(self.watch.rowCount())])
        s.setValue("ui/splitter_sizes", self.splitter.sizes())
        s.setValue("ui/sidebar_visible", self._is_sidebar_visible())
        s.setValue("intervals/L1_INTERVAL", self.L1_INTERVAL)
        s.setValue("intervals/NET_INTERVAL", self.NET_INTERVAL)
        s.setValue("intervals/L1_ENABLED", self.L1_ENABLED)
        s.setValue("ui/THEME_OVERRIDE", self.theme.override_mode)
        s.setValue("ui/MATCH_SYSTEM_ACCENT", self.theme.match_system_accent)
        s.sync()

    def _open_settings_dialog(self):
        from .settings_dialog import SettingsDialog
        cv = {
            "L1_INTERVAL": self.L1_INTERVAL,
            "NET_INTERVAL": self.NET_INTERVAL,
            "L1_ENABLED": self.L1_ENABLED,
            "THEME_OVERRIDE": self._settings().value("ui/THEME_OVERRIDE", getattr(self.theme, "override_mode", "System")),
            "MATCH_SYSTEM_ACCENT": self._settings().value("ui/MATCH_SYSTEM_ACCENT", getattr(self.theme, "match_system_accent", True), type=bool),
            "GOAL_PRESET_1": float(self._settings().value("goals/preset_1", 250000.0) or 250000.0),
            "GOAL_PRESET_2": float(self._settings().value("goals/preset_2", 500000.0) or 500000.0),
            "GOAL_PRESET_3": float(self._settings().value("goals/preset_3", 1000000.0) or 1000000.0),
            "TRADE_DEFAULT_QUANTITY": int(self._settings().value("trade_defaults/default_quantity", 1) or 1),
            "TRADE_QUANTITY_INCREMENT": int(self._settings().value("trade_defaults/quantity_increment", 1) or 1),
        }
        dlg = SettingsDialog(self, self._settings(), cv)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.get_values()
        self.L1_INTERVAL = int(vals["L1_INTERVAL"])
        self.NET_INTERVAL = int(vals["NET_INTERVAL"])
        self.L1_ENABLED = bool(vals["L1_ENABLED"])
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
        self.timer_net.setInterval(self.NET_INTERVAL)
        self.timer_l1.start() if self.L1_ENABLED else self.timer_l1.stop()
        self._save_settings()
        # Goal preset values are global; push to all tabs.
        for tab in self._portfolio_tabs.values():
            tab.reload_goal_presets()

    def _open_user_account_dialog(self):
        dlg = UserAccountDialog(self, self._settings())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._rebuild_portfolio_tabs()

    # ---- Portfolio tab management (Fix #3) ----

    def _build_portfolio_tabs(self):
        """Create one PortfolioTab per account."""
        for account in self._get_account_names():
            tab = PortfolioTab(account, self._settings(), self)
            self.tabs.addTab(tab, account)
            self._portfolio_tabs[account] = tab
        # Connect after all tabs exist so init-time migration saves don't
        # trigger cross-tab reloads before siblings are constructed.
        for tab in self._portfolio_tabs.values():
            tab.tradesChanged.connect(self._on_portfolio_data_changed)

    def _rebuild_portfolio_tabs(self):
        """Tear down and recreate tabs after account list changes."""
        for tab in list(self._portfolio_tabs.values()):
            try:
                tab.tradesChanged.disconnect(self._on_portfolio_data_changed)
            except Exception:
                pass
            idx = self.tabs.indexOf(tab)
            if idx >= 0:
                self.tabs.removeTab(idx)
        self._portfolio_tabs.clear()
        self._build_portfolio_tabs()
        for tab in self._portfolio_tabs.values():
            tab.sync_goal_dashboard_accounts()

    def _current_portfolio_tab(self) -> Optional[PortfolioTab]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, PortfolioTab) else None

    def _on_portfolio_data_changed(self):
        """Refresh all sibling tabs when one tab's trades or goal settings change."""
        sender = self.sender()
        for tab in self._portfolio_tabs.values():
            if tab is not sender:
                tab.reload_from_settings()

    # ---- UI ----

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

        file_menu = self.menuBar().addMenu("&File")
        act_settings = file_menu.addAction("Settings")
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._open_settings_dialog)
        file_menu.addAction("User Account").triggered.connect(self._open_user_account_dialog)
        file_menu.addSeparator()
        file_menu.addAction("Quit").triggered.connect(self.close)

        view_menu = self.menuBar().addMenu("&View")
        self.act_toggle_sidebar = view_menu.addAction("Toggle Sidebar")
        self.act_toggle_sidebar.setCheckable(True)
        self.act_toggle_sidebar.setShortcut(QKeySequence("Ctrl+B"))
        self.act_toggle_sidebar.triggered.connect(self._toggle_sidebar)
        view_menu.addAction("Trade History Columns").triggered.connect(
            lambda: (tab := self._current_portfolio_tab()) and tab.open_trade_history_view_settings()
        )
        view_menu.addAction("Goal Dashboard Accounts").triggered.connect(
            lambda: (tab := self._current_portfolio_tab()) and tab.open_goal_dashboard_accounts_dialog()
        )

        status_corner = QWidget(self)
        sr = QHBoxLayout(status_corner)
        sr.setContentsMargins(8, 0, 8, 0)
        sr.setSpacing(8)
        sr.addWidget(self.spinner)
        sr.addWidget(self.lbl_updating)
        sr.addWidget(self.lbl_status)
        sr.addWidget(self.progress)
        self.menuBar().setCornerWidget(status_corner, Qt.Corner.TopRightCorner)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter)

        # Left: watchlist
        left_wrap = QFrame()
        left_wrap.setObjectName("leftPane")
        left_layout = QVBoxLayout(left_wrap)
        title_row = QHBoxLayout()
        lbl = QLabel("Watchlist")
        lbl.setObjectName("leftTitle")
        self.sort_mode = QComboBox()
        self.sort_mode.addItems([self.SORT_DEFAULT, self.SORT_ALPHA, self.SORT_INDUSTRY, self.SORT_PRICE])
        self.sort_mode.currentTextChanged.connect(self._on_sort_mode_changed)
        self.sort_mode.setFixedWidth(170)
        title_row.addWidget(lbl)
        title_row.addStretch(1)
        title_row.addWidget(QLabel("Sort:"))
        title_row.addWidget(self.sort_mode)
        left_layout.addLayout(title_row)

        self.watch = WatchTable(self)
        self.watch.renameRequested.connect(self._ctx_rename_selected)
        self.watch.moveRequested.connect(self._ctx_move_row)
        left_layout.addWidget(self.watch, stretch=1)

        wl_btns = QHBoxLayout()
        self.add_btn = QPushButton("+ Add")
        self.add_btn.clicked.connect(self._on_add_ticker)
        self.remove_btn = QPushButton("- Remove")
        self.remove_btn.clicked.connect(self._on_remove_ticker)
        wl_btns.addWidget(self.add_btn)
        wl_btns.addWidget(self.remove_btn)
        left_layout.addLayout(wl_btns)
        self.splitter.addWidget(left_wrap)
        self.splitter.setStretchFactor(0, 0)

        # Right: one tab per account
        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)
        self._build_portfolio_tabs()
        self.splitter.addWidget(right_wrap)
        self.splitter.setStretchFactor(1, 1)

        self.statusBar().showMessage("Ready")

    # ---- Timers ----

    def _init_timers(self):
        self.timer_l1 = QTimer(self)
        self.timer_l1.setInterval(self.L1_INTERVAL)
        self.timer_l1.timeout.connect(self._level1_tick)
        self.timer_net = QTimer(self)
        self.timer_net.setInterval(self.NET_INTERVAL)
        self.timer_net.timeout.connect(self._kick_netcheck)
        self.timer_l1.start() if self.L1_ENABLED else self.timer_l1.stop()
        self.timer_net.start()
        self._kick_netcheck()
        self._level1_tick()

    def _kick_netcheck(self):
        w = NetCheckWorker()
        th = QThread(self)
        w.moveToThread(th)
        th.started.connect(w.run)
        w.done.connect(lambda ok: self._on_net_status(ok, th, w))
        th.finished.connect(th.deleteLater)
        th.start()

    def _on_net_status(self, ok: bool, thread: QThread, worker):
        self._online = ok
        dot = "●"
        if ok:
            self.lbl_status.setText(f"{dot} Online")
            self.lbl_status.setStyleSheet("color: #22c55e;")
        else:
            self.lbl_status.setText(f"{dot} Offline")
            self.lbl_status.setStyleSheet("color: #ef4444;")
        thread.quit()

    def _busy_enter(self):
        self._busy_ops += 1
        if self._busy_ops == 1:
            self.spinner.start(90)
            self.lbl_updating.setText("Updating...")

    def _busy_leave(self):
        self._busy_ops = max(0, self._busy_ops - 1)
        if self._busy_ops == 0:
            self.spinner.stop()
            self.lbl_updating.setText("")

    # ---- Marks refresh ----

    def _level1_tick(self):
        tickers = [self.watch.item(r, 0).text() for r in range(self.watch.rowCount())]
        for tab in self._portfolio_tabs.values():
            tickers.extend(tab.holdings_symbols())
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

    def _on_marks(self, data: Dict[str, Dict], thread: QThread, worker):
        # All tabs get the full data dict so cross-account goal calc works.
        for tab in self._portfolio_tabs.values():
            tab.update_marks(data)
        for r in range(self.watch.rowCount()):
            sym = self.watch.item(r, 0).text()
            row = data.get(sym, {})
            cell = self.watch.item(r, 1)
            if cell is None:
                cell = QTableWidgetItem("--")
                self.watch.setItem(r, 1, cell)
            if row.get("price") is not None:
                cell.setText(f"{row['price']:.2f}")
        thread.quit()
        self._busy_leave()

    def _on_marks_error(self, msg: str, thread: QThread, worker):
        self.lbl_status.setText("● Offline")
        self.lbl_status.setStyleSheet("color: #ef4444;")
        thread.quit()
        self._busy_leave()

    def _bind_shortcuts(self):
        act = QAction("Refresh Marks (F5)", self)
        act.setShortcut(QKeySequence("F5"))
        act.triggered.connect(self._level1_tick)
        self.addAction(act)

    # ---- Sidebar ----

    def _is_sidebar_visible(self):
        return self.splitter.sizes()[0] > 0

    def _set_sidebar_visible(self, visible: bool, apply_sizes: bool = True):
        sizes = self.splitter.sizes()
        total = sum(sizes) if sizes else 1000
        if visible:
            left = getattr(self, "_last_sidebar_size", 240) or 240
            if apply_sizes:
                self.splitter.setSizes([left, max(1, total - left)])
            self.act_toggle_sidebar.setChecked(True)
        else:
            if sizes and sizes[0] > 0:
                self._last_sidebar_size = sizes[0]
            if apply_sizes:
                self.splitter.setSizes([0, total])
            self.act_toggle_sidebar.setChecked(False)

    def _toggle_sidebar(self):
        self._set_sidebar_visible(not self._is_sidebar_visible())

    # ---- Watchlist ----

    def _add_watch_row(self, sym: str, mark: str = "--", industry: str = "--"):
        r = self.watch.rowCount()
        self.watch.insertRow(r)
        it0 = QTableWidgetItem(sym.upper())
        f = it0.font(); f.setBold(True); it0.setFont(f)
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
        if not ok or not text.strip(): return
        sym = text.strip().upper()
        if not all(ch.isalnum() or ch in ".-" for ch in sym):
            QMessageBox.warning(self, "Invalid symbol", "Use letters, numbers, dot or dash only.")
            return
        for r in range(self.watch.rowCount()):
            if self.watch.item(r, 0).text() == sym:
                self.watch.selectRow(r); return
        self._add_watch_row(sym)
        self.watch.selectRow(self.watch.rowCount() - 1)
        if self.sort_mode.currentText() == self.SORT_DEFAULT:
            self._save_settings()

    def _on_remove_ticker(self):
        r = self._watch_current_row()
        if r < 0:
            QMessageBox.information(self, "Select item", "Pick a ticker to remove."); return
        sym = self.watch.item(r, 0).text()
        if QMessageBox.question(self, "Remove", f"Remove {sym} from watchlist?") != QMessageBox.StandardButton.Yes:
            return
        self.watch.removeRow(r)
        if self.sort_mode.currentText() == self.SORT_DEFAULT:
            self._save_settings()

    def _ctx_rename_selected(self):
        r = self._watch_current_row()
        if r < 0: return
        old = self.watch.item(r, 0).text()
        text, ok = QInputDialog.getText(self, "Rename ticker", "Symbol:", text=old)
        if not ok or not text.strip(): return
        sym = text.strip().upper()
        if not all(ch.isalnum() or ch in ".-" for ch in sym):
            QMessageBox.warning(self, "Invalid symbol", "Use letters, numbers, dot or dash only."); return
        for rr in range(self.watch.rowCount()):
            if rr != r and self.watch.item(rr, 0).text() == sym:
                QMessageBox.information(self, "Duplicate", f"{sym} is already in the list."); return
        self.watch.item(r, 0).setText(sym)

    def _ctx_move_row(self, delta: int):
        if self.sort_mode.currentText() != self.SORT_DEFAULT:
            QMessageBox.information(self, "Reorder disabled", "Switch to Default (custom) sort to reorder.")
            return
        r = self._watch_current_row()
        if r < 0: return
        new_r = r + delta
        if not (0 <= new_r < self.watch.rowCount()): return
        data = [self.watch.item(r, c).text() for c in range(3)]
        self.watch.removeRow(r)
        self.watch.insertRow(new_r)
        for c, text in enumerate(data):
            item = QTableWidgetItem(text)
            if c == 0:
                f = item.font(); f.setBold(True); item.setFont(f)
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
            rows.append([self.watch.item(r, c).text() if self.watch.item(r, c) else "" for c in range(3)])

        def key(row):
            v = row[col]
            if numeric:
                try: return float(v.replace(",", "")) if v not in ("", "--") else float("-inf")
                except Exception: return float("-inf")
            return v.lower() if case_insensitive else v

        rows.sort(key=key)
        self.watch.setRowCount(0)
        for sym, mark, ind in rows:
            self._add_watch_row(sym, mark, ind)
        if self.watch.rowCount() > 0:
            self.watch.selectRow(0)
