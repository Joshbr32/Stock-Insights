import json
from typing import Dict, List, Optional
from PySide6.QtCore import Qt, QSettings, QTimer, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .theme import ThemeManager
from .widgets import SpinnerLabel, WatchTable
from .workers import MarksWorker, NetCheckWorker
from .logging_utils import setup_logging, serial_debug
from .portfolio_tab import PortfolioTab
from .api_client import DataStore, FallbackDataStore, LocalDataStore, RemoteDataStore

_ORG = "StockInsights"
_APP = "StocksGUI"


# ---------------------------------------------------------------------------
# Admin: User Account Management Dialog
# ---------------------------------------------------------------------------

class UserAccountDialog(QDialog):
    """Create / view user accounts (admin-only management + self password change)."""

    def __init__(self, store: DataStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("User Account")
        self.resize(520, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        s = QSettings(_ORG, _APP)

        # ---- Profile group ----
        profile_grp = QGroupBox("Profile")
        profile_grid = QGridLayout(profile_grp)
        profile_grid.setContentsMargins(14, 18, 14, 14)
        profile_grid.setHorizontalSpacing(12)
        profile_grid.setVerticalSpacing(10)

        info = store.user_info
        profile_grid.addWidget(QLabel("Username:"), 0, 0)
        profile_grid.addWidget(QLabel(info.get("username", "")), 0, 1)
        profile_grid.addWidget(QLabel("Role:"), 1, 0)
        profile_grid.addWidget(QLabel("Admin" if info.get("is_admin") else "User"), 1, 1)
        profile_grid.addWidget(QLabel("Server:"), 2, 0)

        server_url = ""
        if isinstance(store, RemoteDataStore):
            server_url = store._base
        profile_grid.addWidget(QLabel(server_url or "(offline)"), 2, 1)
        root.addWidget(profile_grp)

        # ---- Change password ----
        pwd_grp = QGroupBox("Change Password")
        pwd_form = QVBoxLayout(pwd_grp)
        pwd_form.setContentsMargins(14, 18, 14, 14)
        self.new_pass_edit = QLineEdit()
        self.new_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pass_edit.setPlaceholderText("New password (leave blank to keep current)")
        btn_change_pwd = QPushButton("Change Password")
        btn_change_pwd.clicked.connect(self._change_password)
        pwd_form.addWidget(self.new_pass_edit)
        pwd_form.addWidget(btn_change_pwd)
        root.addWidget(pwd_grp)

        # ---- Accounts list ----
        accts_grp = QGroupBox("My Accounts")
        accts_layout = QVBoxLayout(accts_grp)
        accts_layout.setContentsMargins(14, 18, 14, 14)
        accts_layout.setSpacing(8)

        self.accounts_list = QListWidget()
        for acct in store.get_account_names():
            self.accounts_list.addItem(acct)
        accts_layout.addWidget(self.accounts_list)

        acct_btns = QHBoxLayout()
        btn_add = QPushButton("+ Add Account")
        btn_remove = QPushButton("- Remove Account")
        btn_add.clicked.connect(self._add_account)
        btn_remove.clicked.connect(self._remove_account)
        acct_btns.addWidget(btn_add)
        acct_btns.addWidget(btn_remove)
        acct_btns.addStretch(1)
        accts_layout.addLayout(acct_btns)
        root.addWidget(accts_grp)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def _change_password(self):
        password = self.new_pass_edit.text().strip()
        if not password:
            return
        if not isinstance(self._store, RemoteDataStore):
            QMessageBox.information(self, "Offline", "Password change requires a server connection.")
            return
        try:
            import requests
            user_id = self._store.user_info["user_id"]
            r = requests.put(
                f"{self._store._base}/users/{user_id}/password",
                json={"new_password": password},
                headers=self._store._headers(),
                timeout=8,
            )
            if r.ok:
                QMessageBox.information(self, "Success", "Password changed.")
                self.new_pass_edit.clear()
            else:
                QMessageBox.warning(self, "Error", r.text)
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))

    def _add_account(self):
        text, ok = QInputDialog.getText(self, "Add Account", "Account name:")
        if not ok or not text.strip(): return
        name = text.strip()
        existing = self._store.get_account_names()
        if name in existing:
            QMessageBox.information(self, "Duplicate", f"'{name}' already exists."); return
        try:
            self._store.save_accounts(existing + [name])
            self.accounts_list.addItem(name)
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))

    def _remove_account(self):
        item = self.accounts_list.currentItem()
        if not item: return
        name = item.text()
        existing = self._store.get_account_names()
        if len(existing) <= 1:
            QMessageBox.information(self, "Cannot Remove", "At least one account must remain."); return
        if QMessageBox.question(self, "Remove Account", f"Remove '{name}'? This deletes all its trades.") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.save_accounts([a for a in existing if a != name])
            self.accounts_list.takeItem(self.accounts_list.row(item))
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))


# ---------------------------------------------------------------------------
# Admin: portfolio viewer for another user (read-only window)
# ---------------------------------------------------------------------------

class UserPortfolioViewer(QMainWindow):
    """Read-only portfolio window opened by an admin to view another user's data."""

    closed = Signal()   # emitted from closeEvent after clean shutdown

    def __init__(self, user_store: DataStore, username: str, settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Viewing Portfolio — {username}")
        self.resize(1100, 750)
        self._store = user_store
        self._settings = settings
        self._tabs: Dict[str, PortfolioTab] = {}
        self._closing = False
        self._active_marks_thread: Optional[QThread] = None
        self._active_marks_worker = None   # keep worker alive while thread runs

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        banner = QLabel(f"  👁  Admin view — {username}'s portfolios (read-only)")
        banner.setStyleSheet(
            "background: #7c3aed; color: white; padding: 6px 12px; font-weight: bold;"
        )
        layout.addWidget(banner)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        try:
            accounts = user_store.get_account_names()
        except Exception:
            accounts = []

        for account in accounts:
            tab = PortfolioTab(
                account_name=account,
                store=user_store,
                settings=settings,
                read_only=True,
                parent=self,
            )
            self.tab_widget.addTab(tab, account)
            self._tabs[account] = tab

        if not accounts:
            self.tab_widget.addTab(QLabel("No accounts found."), "—")

        # Refresh marks periodically
        self._marks_timer = QTimer(self)
        self._marks_timer.setInterval(30_000)
        self._marks_timer.timeout.connect(self._refresh_marks)
        self._marks_timer.start()
        self._refresh_marks()

    def _refresh_marks(self):
        if self._closing:
            return
        # Skip if a fetch is already in flight
        if self._active_marks_thread is not None and self._active_marks_thread.isRunning():
            return
        tickers: List[str] = []
        for tab in self._tabs.values():
            tickers.extend(tab.holdings_symbols())
        tickers = list(dict.fromkeys([t for t in tickers if t]))
        if not tickers:
            return
        # Store worker as instance var — local var would be GC'd when this
        # function returns, destroying the worker while the thread is running it.
        self._active_marks_worker = MarksWorker(tickers)
        th = QThread(self)
        self._active_marks_worker.moveToThread(th)
        th.started.connect(self._active_marks_worker.run)
        self._active_marks_worker.done.connect(lambda data, t=th: self._on_marks(data, t))
        self._active_marks_worker.error.connect(lambda _, t=th: t.quit())
        th.finished.connect(th.deleteLater)
        def _cleanup():
            self._active_marks_thread = None
            self._active_marks_worker = None
        th.finished.connect(_cleanup)
        self._active_marks_thread = th
        th.start()

    def _on_marks(self, data: dict, thread: QThread):
        if self._closing:
            thread.quit()
            return
        for tab in self._tabs.values():
            tab.update_marks(data)
        thread.quit()

    def closeEvent(self, event):
        """Cleanly shut down before GC.

        Crash sequence (now fixed):
          1. closeEvent fires, _viewer_windows.pop() drops last Python ref
          2. Python GC collects the viewer
          3. Marks thread finishes ~2s later, callback fires into dead self -> crash

        Fix: set _closing flag immediately, wait for any active thread to
        finish, THEN emit closed() which triggers the pop and allows GC.
        """
        self._closing = True
        self._marks_timer.stop()
        try:
            self._marks_timer.timeout.disconnect()
        except Exception:
            pass

        # Disconnect and wait for any in-flight marks thread (usually <3s)
        if self._active_marks_thread is not None and self._active_marks_thread.isRunning():
            try:
                self._active_marks_thread.disconnect()
            except Exception:
                pass
            self._active_marks_thread.quit()
            self._active_marks_thread.wait(4000)
            self._active_marks_thread = None
            self._active_marks_worker = None   # release worker ref after thread done

        self._tabs.clear()
        event.accept()
        self.closed.emit()   # triggers _viewer_windows.pop() in MainWindow


# ---------------------------------------------------------------------------
# Admin: user selection dialog
# ---------------------------------------------------------------------------

class SelectUserDialog(QDialog):
    def __init__(self, users: List[dict], current_user_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select User to View")
        self.resize(360, 280)
        self._selected: Optional[dict] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        root.addWidget(QLabel("Select a user to open their portfolio in a read-only window:"))

        self.list_widget = QListWidget()
        for user in users:
            if user["id"] == current_user_id:
                continue  # skip self
            item = QListWidgetItem(f"{'[Admin] ' if user['is_admin'] else ''}{user['username']}")
            item.setData(Qt.ItemDataRole.UserRole, user)
            self.list_widget.addItem(item)
        root.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.list_widget.doubleClicked.connect(self._accept)

    def _accept(self):
        item = self.list_widget.currentItem()
        if item:
            self._selected = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def selected_user(self) -> Optional[dict]:
        return self._selected


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    ORG = _ORG
    APP = _APP

    SORT_DEFAULT = "Default (custom)"
    SORT_ALPHA = "Alphabetical"
    SORT_INDUSTRY = "Industry"
    SORT_PRICE = "Price"

    L1_INTERVAL = 20_000
    NET_INTERVAL = 10_000
    L1_ENABLED = True

    def __init__(self, store: DataStore):
        super().__init__()
        setup_logging()
        serial_debug("MainWindow init start")
        self._store = store
        # Wire offline/online callbacks if using FallbackDataStore
        if isinstance(store, FallbackDataStore):
            store._on_offline_cb = self._set_offline_status
            store._on_online_cb  = self._set_synced_status
        self.setWindowTitle(f"Stock Insights — {store.username}")
        self.resize(1200, 800)
        self._last_sidebar_size = 240
        self._busy_ops = 0
        self._online = True
        self._portfolio_tabs: Dict[str, PortfolioTab] = {}
        self._viewer_windows: Dict[int, UserPortfolioViewer] = {}  # user_id -> window
        self._reconnect_timer_obj = None   # QTimer for reconnect attempts

        self._build_ui()
        self.theme = ThemeManager(self)
        self.theme.apply()
        self.theme.start_watching()
        self._load_settings()
        self._bind_shortcuts()
        self._init_timers()
        self._init_reconnect_timer()
        serial_debug("MainWindow init done")

    # ---- QSettings (device-local UI prefs only) ----

    def _qsettings(self) -> QSettings:
        return QSettings(self.ORG, self.APP)

    def _load_settings(self):
        s = self._qsettings()

        # Watchlist — load from store (synced), fall back to QSettings for migration
        try:
            items = self._store.get_watchlist()
        except Exception:
            items = []
        if not items:
            items_qs = s.value("watchlist/items", [])
            if isinstance(items_qs, str):
                try: items_qs = json.loads(items_qs)
                except Exception: items_qs = []
            items = [str(t).upper() for t in items_qs] if items_qs else ["NVDA", "SRPT", "RDDT", "FIG", "NCLH", "CCL"]

        self.watch.setRowCount(0)
        for sym in items:
            self._add_watch_row(sym)

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
            except Exception: pass
        self._set_sidebar_visible(sidebar_visible, apply_sizes=False)

    def _save_settings(self):
        s = self._qsettings()
        # Save watchlist to store (synced) AND to QSettings (offline fallback)
        symbols = [self.watch.item(r, 0).text() for r in range(self.watch.rowCount())]
        try:
            self._store.save_watchlist(symbols)
        except Exception:
            pass
        s.setValue("watchlist/items", symbols)
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
        s = self._qsettings()
        cv = {
            "L1_INTERVAL": self.L1_INTERVAL, "NET_INTERVAL": self.NET_INTERVAL,
            "L1_ENABLED": self.L1_ENABLED,
            "THEME_OVERRIDE": s.value("ui/THEME_OVERRIDE", getattr(self.theme, "override_mode", "System")),
            "MATCH_SYSTEM_ACCENT": s.value("ui/MATCH_SYSTEM_ACCENT",
                                            getattr(self.theme, "match_system_accent", True), type=bool),
            "TRADE_DEFAULT_QUANTITY": int(s.value("trade_defaults/default_quantity", 1) or 1),
            "TRADE_QUANTITY_INCREMENT": int(s.value("trade_defaults/quantity_increment", 1) or 1),
        }
        dlg = SettingsDialog(self, s, cv)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        vals = dlg.get_values()
        self.L1_INTERVAL = int(vals["L1_INTERVAL"])
        self.NET_INTERVAL = int(vals["NET_INTERVAL"])
        self.L1_ENABLED = bool(vals["L1_ENABLED"])
        self.theme.set_override_mode(vals["THEME_OVERRIDE"])
        self.theme.set_match_system_accent(vals["MATCH_SYSTEM_ACCENT"])
        s = self._qsettings()
        s.setValue("ui/THEME_OVERRIDE", self.theme.override_mode)
        s.setValue("ui/MATCH_SYSTEM_ACCENT", self.theme.match_system_accent)
        s.setValue("trade_defaults/default_quantity", int(vals["TRADE_DEFAULT_QUANTITY"]))
        s.setValue("trade_defaults/quantity_increment", int(vals["TRADE_QUANTITY_INCREMENT"]))
        s.sync()
        self.timer_l1.setInterval(self.L1_INTERVAL)
        self.timer_net.setInterval(self.NET_INTERVAL)
        self.timer_l1.start() if self.L1_ENABLED else self.timer_l1.stop()
        self._save_settings()

    def _open_user_account_dialog(self):
        dlg = UserAccountDialog(self._store, self)
        dlg.exec()
        # Rebuild tabs in case accounts changed
        self._rebuild_portfolio_tabs()

    # ---- Portfolio tab management ----

    def _build_portfolio_tabs(self):
        try:
            accounts = self._store.get_account_names()
        except Exception:
            accounts = ["Default"]
        s = self._qsettings()
        for account in accounts:
            tab = PortfolioTab(
                account_name=account,
                store=self._store,
                settings=s,
                read_only=False,
                parent=self,
            )
            self.tabs.addTab(tab, account)
            self._portfolio_tabs[account] = tab
        for tab in self._portfolio_tabs.values():
            tab.tradesChanged.connect(self._on_portfolio_data_changed)

    def _rebuild_portfolio_tabs(self):
        for tab in list(self._portfolio_tabs.values()):
            try: tab.tradesChanged.disconnect(self._on_portfolio_data_changed)
            except Exception: pass
            idx = self.tabs.indexOf(tab)
            if idx >= 0: self.tabs.removeTab(idx)
        self._portfolio_tabs.clear()
        self._build_portfolio_tabs()
        for tab in self._portfolio_tabs.values():
            tab.sync_goal_dashboard_accounts()

    def _current_portfolio_tab(self) -> Optional[PortfolioTab]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, PortfolioTab) else None

    def _on_portfolio_data_changed(self):
        sender = self.sender()
        for tab in self._portfolio_tabs.values():
            if tab is not sender:
                tab.reload_from_store()

    # ---- Admin: view another user's portfolio ----

    def _open_view_user_portfolio(self):
        if not self._store.is_admin:
            QMessageBox.information(self, "Admin Only", "Only admin accounts can view other users' portfolios.")
            return
        if not isinstance(self._store, RemoteDataStore):
            QMessageBox.information(self, "Server Required", "Viewing other users requires a server connection.")
            return
        try:
            users = self._store.list_users()
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Could not fetch user list: {exc}")
            return

        dlg = SelectUserDialog(users, self._store.user_info["user_id"], self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        user = dlg.selected_user()
        if user is None:
            return

        user_id = user["id"]
        # Reuse existing window if open
        if user_id in self._viewer_windows:
            w = self._viewer_windows[user_id]
            w.raise_(); w.activateWindow(); return

        user_store = self._store.store_for_user(user_id, user["username"])
        viewer = UserPortfolioViewer(user_store, user["username"], self._qsettings(), parent=None)
        # Do NOT set WA_DeleteOnClose — the marks timer can still fire into a
        # C++-deleted object and crash the main window on the next click.
        # closeEvent on the viewer handles cleanup; Python GC owns the lifetime.
        viewer.closed.connect(lambda uid=user_id: self._viewer_windows.pop(uid, None))
        self._viewer_windows[user_id] = viewer
        viewer.show()

    # ---- UI ----

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        self.spinner = SpinnerLabel()
        self.lbl_updating = QLabel("")
        self.lbl_status = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(120)
        self.progress.setVisible(False)

        # ---- Menus ----
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
        view_menu.addAction("Trade History Columns").triggered.connect(self._open_trade_history_columns)
        view_menu.addAction("Goal Dashboard Options").triggered.connect(self._open_goal_dashboard_options)

        # Admin menu (always built; items shown/hidden based on role)
        admin_menu = self.menuBar().addMenu("&Admin")
        self.act_view_user_portfolio = admin_menu.addAction("View User Portfolio...")
        self.act_view_user_portfolio.triggered.connect(self._open_view_user_portfolio)
        self.act_view_user_portfolio.setVisible(self._store.is_admin)

        # Status corner
        status_corner = QWidget(self)
        sr = QHBoxLayout(status_corner)
        sr.setContentsMargins(8, 0, 8, 0); sr.setSpacing(8)
        sr.addWidget(self.spinner); sr.addWidget(self.lbl_updating)
        sr.addWidget(self.lbl_status); sr.addWidget(self.progress)
        self.menuBar().setCornerWidget(status_corner, Qt.Corner.TopRightCorner)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(self.splitter)

        # Left: Watchlist
        left_wrap = QFrame()
        left_wrap.setObjectName("leftPane")
        left_layout = QVBoxLayout(left_wrap)
        title_row = QHBoxLayout()
        lbl = QLabel("Watchlist"); lbl.setObjectName("leftTitle")
        self.sort_mode = QComboBox()
        self.sort_mode.addItems([self.SORT_DEFAULT, self.SORT_ALPHA, self.SORT_INDUSTRY, self.SORT_PRICE])
        self.sort_mode.currentTextChanged.connect(self._on_sort_mode_changed)
        self.sort_mode.setFixedWidth(170)
        title_row.addWidget(lbl); title_row.addStretch(1)
        title_row.addWidget(QLabel("Sort:")); title_row.addWidget(self.sort_mode)
        left_layout.addLayout(title_row)
        self.watch = WatchTable(self)
        self.watch.renameRequested.connect(self._ctx_rename_selected)
        self.watch.moveRequested.connect(self._ctx_move_row)
        left_layout.addWidget(self.watch, stretch=1)
        wl_btns = QHBoxLayout()
        self.add_btn = QPushButton("+ Add"); self.add_btn.clicked.connect(self._on_add_ticker)
        self.remove_btn = QPushButton("- Remove"); self.remove_btn.clicked.connect(self._on_remove_ticker)
        wl_btns.addWidget(self.add_btn); wl_btns.addWidget(self.remove_btn)
        left_layout.addLayout(wl_btns)
        self.splitter.addWidget(left_wrap)
        self.splitter.setStretchFactor(0, 0)

        # Right: per-account tabs
        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)
        self._build_portfolio_tabs()
        self.splitter.addWidget(right_wrap)
        self.splitter.setStretchFactor(1, 1)

        self.statusBar().showMessage("Ready")

    # ---- View menu ----

    def _open_trade_history_columns(self):
        tab = self._current_portfolio_tab()
        if tab: tab.open_trade_history_view_settings()

    def _open_goal_dashboard_options(self):
        tab = self._current_portfolio_tab()
        if tab: tab.open_goal_dashboard_options_dialog()

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
        if ok:
            self.lbl_status.setText("● Online"); self.lbl_status.setStyleSheet("color: #22c55e;")
        else:
            self.lbl_status.setText("● Offline"); self.lbl_status.setStyleSheet("color: #ef4444;")
        thread.quit()

    def _init_reconnect_timer(self):
        """Start a 30-second reconnect timer if we are using FallbackDataStore."""
        if not isinstance(self._store, FallbackDataStore):
            return
        self._reconnect_timer_obj = QTimer(self)
        self._reconnect_timer_obj.setInterval(30_000)
        self._reconnect_timer_obj.timeout.connect(self._attempt_reconnect)
        self._reconnect_timer_obj.start()

    def _attempt_reconnect(self):
        """Try to re-establish server connection and flush queued writes."""
        if not isinstance(self._store, FallbackDataStore):
            return
        if self._store._is_online:
            return   # already online, nothing to do
        serial_debug("Attempting reconnect to server...")
        # Run in a thread so it doesn't block the UI
        th = QThread(self)
        th.started.connect(lambda: self._do_reconnect(th))
        th.finished.connect(th.deleteLater)
        th.start()

    def _do_reconnect(self, thread: QThread):
        try:
            ok = self._store.attempt_reconnect()
        except Exception:
            ok = False
        # Signal back to main thread via a queued connection
        from PySide6.QtCore import QMetaObject, Qt as _Qt
        if ok:
            QMetaObject.invokeMethod(self, "_on_reconnected", _Qt.ConnectionType.QueuedConnection)
        thread.quit()

    def _on_reconnected(self):
        """Called on main thread after successful reconnect."""
        pending = self._store.pending_sync_count
        if pending == 0:
            self.lbl_status.setText("● Online")
            self.lbl_status.setStyleSheet("color: #22c55e;")
        else:
            self.lbl_status.setText(f"● Online — syncing...")
            self.lbl_status.setStyleSheet("color: #22c55e;")
        # Reload all tabs so they get fresh server data
        for tab in self._portfolio_tabs.values():
            tab.reload_from_store()

    def _set_offline_status(self, n_pending: int):
        """Called by FallbackDataStore when a write fails and is queued."""
        self.lbl_status.setText(f"● Offline — {n_pending} change{'s' if n_pending != 1 else ''} queued")
        self.lbl_status.setStyleSheet("color: #f59e0b;")   # amber

    def _set_synced_status(self, synced_count: int):
        """Called by FallbackDataStore after successfully flushing queued writes."""
        if synced_count > 0:
            self.lbl_status.setText(f"● Online — synced {synced_count} change{'s' if synced_count != 1 else ''}")
        else:
            self.lbl_status.setText("● Online")
        self.lbl_status.setStyleSheet("color: #22c55e;")

    def _busy_enter(self):
        self._busy_ops += 1
        if self._busy_ops == 1:
            self.spinner.start(90); self.lbl_updating.setText("Updating...")

    def _busy_leave(self):
        self._busy_ops = max(0, self._busy_ops - 1)
        if self._busy_ops == 0:
            self.spinner.stop(); self.lbl_updating.setText("")

    def _level1_tick(self):
        tickers = [self.watch.item(r, 0).text() for r in range(self.watch.rowCount())]
        for tab in self._portfolio_tabs.values():
            tickers.extend(tab.holdings_symbols())
        tickers = list(dict.fromkeys([t for t in tickers if t]))
        if not tickers: return
        self._busy_enter()
        # Store worker as instance var so it isn't GC'd while the thread runs it.
        self._marks_worker = MarksWorker(tickers)
        th = QThread(self)
        self._marks_worker.moveToThread(th)
        th.started.connect(self._marks_worker.run)
        self._marks_worker.done.connect(lambda data, t=th: self._on_marks(data, t, self._marks_worker))
        self._marks_worker.error.connect(lambda msg, t=th: self._on_marks_error(msg, t, self._marks_worker))
        th.finished.connect(th.deleteLater)
        th.finished.connect(lambda: setattr(self, "_marks_worker", None))
        th.start()

    def _on_marks(self, data: dict, thread: QThread, worker):
        for tab in self._portfolio_tabs.values():
            tab.update_marks(data)
        for r in range(self.watch.rowCount()):
            sym = self.watch.item(r, 0).text()
            row = data.get(sym, {})
            cell = self.watch.item(r, 1)
            if cell is None:
                cell = QTableWidgetItem("--"); self.watch.setItem(r, 1, cell)
            if row.get("price") is not None:
                cell.setText(f"{row['price']:.2f}")
        thread.quit(); self._busy_leave()

    def _on_marks_error(self, msg: str, thread: QThread, worker):
        self.lbl_status.setText("● Offline"); self.lbl_status.setStyleSheet("color: #ef4444;")
        thread.quit(); self._busy_leave()

    def _bind_shortcuts(self):
        act = QAction("Refresh Marks (F5)", self)
        act.setShortcut(QKeySequence("F5"))
        act.triggered.connect(self._level1_tick)
        self.addAction(act)

    # ---- Sidebar ----

    def _is_sidebar_visible(self): return self.splitter.sizes()[0] > 0

    def _set_sidebar_visible(self, visible: bool, apply_sizes: bool = True):
        sizes = self.splitter.sizes()
        total = sum(sizes) if sizes else 1000
        if visible:
            left = getattr(self, "_last_sidebar_size", 240) or 240
            if apply_sizes: self.splitter.setSizes([left, max(1, total - left)])
            self.act_toggle_sidebar.setChecked(True)
        else:
            if sizes and sizes[0] > 0: self._last_sidebar_size = sizes[0]
            if apply_sizes: self.splitter.setSizes([0, total])
            self.act_toggle_sidebar.setChecked(False)

    def _toggle_sidebar(self): self._set_sidebar_visible(not self._is_sidebar_visible())

    # ---- Watchlist ----

    def _add_watch_row(self, sym: str, mark: str = "--", industry: str = "--"):
        r = self.watch.rowCount()
        self.watch.insertRow(r)
        it0 = QTableWidgetItem(sym.upper())
        f = it0.font(); f.setBold(True); it0.setFont(f)
        it0.setFlags(it0.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it1 = QTableWidgetItem(mark); it1.setFlags(it1.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it2 = QTableWidgetItem(industry); it2.setFlags(it2.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.watch.setItem(r, 0, it0); self.watch.setItem(r, 1, it1); self.watch.setItem(r, 2, it2)

    def _watch_current_row(self) -> int: return self.watch.currentRow()

    def _on_add_ticker(self):
        text, ok = QInputDialog.getText(self, "Add ticker", "Symbol:")
        if not ok or not text.strip(): return
        sym = text.strip().upper()
        if not all(ch.isalnum() or ch in ".-" for ch in sym):
            QMessageBox.warning(self, "Invalid symbol", "Use letters, numbers, dot or dash only."); return
        for r in range(self.watch.rowCount()):
            if self.watch.item(r, 0).text() == sym:
                self.watch.selectRow(r); return
        self._add_watch_row(sym)
        self.watch.selectRow(self.watch.rowCount() - 1)
        if self.sort_mode.currentText() == self.SORT_DEFAULT: self._save_settings()

    def _on_remove_ticker(self):
        r = self._watch_current_row()
        if r < 0:
            QMessageBox.information(self, "Select item", "Pick a ticker to remove."); return
        sym = self.watch.item(r, 0).text()
        if QMessageBox.question(self, "Remove", f"Remove {sym} from watchlist?") \
                != QMessageBox.StandardButton.Yes: return
        self.watch.removeRow(r)
        if self.sort_mode.currentText() == self.SORT_DEFAULT: self._save_settings()

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
            QMessageBox.information(self, "Reorder disabled", "Switch to Default (custom) sort to reorder."); return
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
            try:
                items = self._store.get_watchlist()
            except Exception:
                items = []
            if not items:
                items = self._qsettings().value("watchlist/items", []) or []
            self.watch.setRowCount(0)
            for sym in items: self._add_watch_row(str(sym).upper())
        elif mode == self.SORT_ALPHA: self._apply_sort_by_column(0, True, False)
        elif mode == self.SORT_INDUSTRY: self._apply_sort_by_column(2, True, False)
        elif mode == self.SORT_PRICE: self._apply_sort_by_column(1, False, True)

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
        if self.watch.rowCount() > 0: self.watch.selectRow(0)
