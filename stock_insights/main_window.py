"""main_window.py — QML-hosted main window.

The central widget is a QQuickWidget rendering `qml/Main.qml`. All data
exposed to QML lives behind an AppController defined in qml_bridge.py.
Modal dialogs (login, settings, trade edit, etc.) remain QWidget-based —
forms are exactly what QWidget is good at.

What still lives here
─────────────────────
• Menu bar & status corner (online indicator, busy spinner).
• ThemeManager wiring + initial theme application.
• MarksWorker / NetCheckWorker / ReconnectWorker QThread management.
• Watchlist persistence and add/remove/rename slots called by QML.
• Trade CRUD callbacks called by QML — they open the existing
  TradeEditDialog / MarkDownDialog / DoubleDownDialog and persist via
  the DataStore.
• Admin dialogs (UserAccountDialog, UserPortfolioViewer, SelectUserDialog)
  — UserPortfolioViewer still uses the legacy QWidget PortfolioTab.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QSettings, QTimer, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QKeySequence
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .api_client import DataStore, FallbackDataStore, RemoteDataStore
from .logging_utils import get_logger, setup_logging, serial_debug
from .portfolio import Holding, Trade
from .portfolio_tab import (
    DoubleDownDialog,
    FulfillOrderDialog,
    GoalDashboardOptionsDialog,
    MarkDownDialog,
    PortfolioTab,
    TradeEditDialog,
)
from .qml_bridge import AppController
from .theme import ThemeManager
from .widgets import SpinnerLabel
from .workers import MarksWorker, NetCheckWorker, ReconnectWorker

_ORG = "StockInsights"
_APP = "StocksGUI"
_QML_DIR = Path(__file__).resolve().parent / "qml"


# ---------------------------------------------------------------------------
# Admin: User Account Management Dialog (unchanged from QWidget version)
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
        elif isinstance(store, FallbackDataStore):
            server_url = store._remote._base
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
        remote_store = self._remote_store()
        if remote_store is None:
            QMessageBox.information(self, "Offline", "Password change requires a server connection.")
            return
        try:
            import requests
            user_id = remote_store.user_info["user_id"]
            r = requests.put(
                f"{remote_store._base}/users/{user_id}/password",
                json={"new_password": password},
                headers=remote_store._headers(),
                timeout=8,
            )
            if r.ok:
                QMessageBox.information(self, "Success", "Password changed.")
                self.new_pass_edit.clear()
            else:
                QMessageBox.warning(self, "Error", r.text)
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))

    def _remote_store(self) -> Optional[RemoteDataStore]:
        if isinstance(self._store, RemoteDataStore):
            return self._store
        if isinstance(self._store, FallbackDataStore) and self._store._is_online:
            return self._store._remote
        return None

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
# Admin: portfolio viewer for another user (still uses the QWidget PortfolioTab)
# ---------------------------------------------------------------------------

class UserPortfolioViewer(QMainWindow):
    """Read-only portfolio window opened by an admin to view another user's data."""

    closed = Signal()

    def __init__(self, user_store: DataStore, username: str, settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Viewing Portfolio — {username}")
        self.resize(1100, 750)
        self._store = user_store
        self._settings = settings
        self.theme = getattr(parent, "theme", None)
        self._tabs: Dict[str, PortfolioTab] = {}
        self._closing = False
        self._active_marks_thread: Optional[QThread] = None
        self._active_marks_worker = None

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

        self._marks_timer = QTimer(self)
        self._marks_timer.setInterval(30_000)
        self._marks_timer.timeout.connect(self._refresh_marks)
        self._marks_timer.start()
        QTimer.singleShot(500, self._refresh_marks)

    def _refresh_marks(self):
        if self._closing:
            return
        if self._active_marks_thread is not None and self._active_marks_thread.isRunning():
            return
        tickers: List[str] = []
        for tab in self._tabs.values():
            tickers.extend(tab.holdings_symbols())
        tickers = list(dict.fromkeys([t for t in tickers if t]))
        if not tickers:
            return
        worker = MarksWorker(tickers)
        th = QThread(self)
        self._active_marks_worker = worker
        self._active_marks_thread = th
        worker.moveToThread(th)
        th.started.connect(worker.run)
        worker.done.connect(self._on_marks)
        worker.done.connect(th.quit)
        worker.error.connect(th.quit)
        th.finished.connect(worker.deleteLater)
        th.finished.connect(th.deleteLater)

        def _cleanup():
            self._active_marks_thread = None
            self._active_marks_worker = None
        th.finished.connect(_cleanup)
        th.start()

    def _on_marks(self, data: dict):
        if self._closing:
            return
        for tab in self._tabs.values():
            tab.update_marks(data)

    def update_ui(self):
        for tab in self._tabs.values():
            tab.update_ui()
        self.update()

    def closeEvent(self, event):
        self._closing = True
        self._marks_timer.stop()
        try:
            self._marks_timer.timeout.disconnect()
        except Exception:
            pass
        if self._active_marks_thread is not None:
            try:
                if self._active_marks_thread.isRunning():
                    self._active_marks_thread.quit()
                    self._active_marks_thread.wait(4000)
            except Exception:
                pass
            self._active_marks_thread = None
            self._active_marks_worker = None
        self._tabs.clear()
        event.accept()
        self.closed.emit()


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
                continue
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

    L1_INTERVAL = 20_000
    NET_INTERVAL = 10_000
    L1_ENABLED = True
    DEFAULT_WATCHLIST = ["NVDA", "SRPT", "RDDT", "FIG", "NCLH", "CCL"]

    def __init__(self, store: DataStore):
        super().__init__()
        setup_logging()
        serial_debug("MainWindow init start")

        self._store = store
        self._closing = False
        self._busy_ops = 0
        self._online = True
        self._viewer_windows: Dict[int, UserPortfolioViewer] = {}
        self._reconnect_timer_obj: Optional[QTimer] = None
        self._marks_thread: Optional[QThread] = None
        self._marks_worker: Optional[MarksWorker] = None
        self._netcheck_thread: Optional[QThread] = None
        self._netcheck_worker: Optional[NetCheckWorker] = None
        self._reconnect_thread: Optional[QThread] = None
        self._reconnect_worker: Optional[ReconnectWorker] = None

        if isinstance(store, FallbackDataStore):
            store._on_offline_cb = self._set_offline_status
            store._on_online_cb = self._set_synced_status

        self.setWindowTitle(f"Stock Insights — {store.username}")
        self.resize(1280, 820)

        # ── ThemeManager (created early so AppController can reference it) ──
        self.theme = ThemeManager(self)
        s = self._qsettings()
        self.theme.override_mode = s.value("ui/THEME_OVERRIDE", "System")
        self.theme.match_system_accent = s.value("ui/MATCH_SYSTEM_ACCENT", True, type=bool)
        self.theme.theme_name = s.value("ui/THEME_NAME", "Default")
        self.theme.font_size_label = s.value("ui/FONT_SIZE", "Normal")
        self.L1_INTERVAL = int(s.value("intervals/L1_INTERVAL", self.L1_INTERVAL))
        self.NET_INTERVAL = int(s.value("intervals/NET_INTERVAL", self.NET_INTERVAL))
        self.L1_ENABLED = bool(s.value("intervals/L1_ENABLED", True, type=bool))

        # ── AppController bridges store + theme into QML ──
        self._app = AppController(self._store, self.theme, self)
        # All QML-triggered handlers that open modal QDialogs / QMenus run
        # through _safe_run so the QML callback unwinds before the dialog
        # opens (avoids nested-event-loop crashes on Windows + QQuickWidget).
        self._app.set_callbacks({
            "add_ticker": lambda: self._safe_run(self._on_add_ticker),
            "remove_ticker": lambda r: self._safe_run(self._on_remove_ticker, r),
            "rename_ticker": lambda r, s: self._safe_run(self._on_rename_ticker, r, s),
            "refresh_marks": self._level1_tick,  # not a dialog — direct call OK
            "add_trade": lambda: self._safe_run(self._on_add_trade),
            "edit_trade": lambda i: self._safe_run(self._on_edit_trade, i),
            "delete_trade": lambda i: self._safe_run(self._on_delete_trade, i),
            "set_goal_target": self._on_set_goal_target,  # store write — direct call OK
            "open_goal_options": lambda: self._safe_run(self._on_open_goal_options),
            "open_trade_history_options": lambda: self._safe_run(self._on_open_trade_history_options),
            "holdings_menu": lambda i: self._safe_run(self._on_holdings_menu, i),
            "trade_menu": lambda i: self._safe_run(self._on_trade_menu, i),
        })
        self._app.rebuild_accounts()
        # Populate trades / holdings / goal data BEFORE QML is mounted, so
        # the empty-state placeholder text never flashes on screen during
        # the initial render. The data store reads from local cache /
        # QSettings and is fast enough to do synchronously here.
        self._app.refresh_all_accounts()

        self._build_menus()
        self._build_status_corner()
        self._build_qml_host()

        # Apply theme + start watching for OS theme changes.
        self.theme.apply()
        self.theme.themeApplied.connect(self._app.theme.refresh)
        # When the user changes font size, the QML widgets grow proportionally
        # (via app.theme.fontScale); we also bump the window's minimum size
        # so smaller widgets never get cropped when the user drags the edge.
        self.theme.themeApplied.connect(self._apply_minimum_window_size)
        self.theme.start_watching()
        self._apply_minimum_window_size()

        self._load_watchlist()
        self._init_timers()
        self._init_reconnect_timer()

        serial_debug("MainWindow init done")

    # ------------------------------------------------------------------
    # Minimum window size (scales with font size)
    # ------------------------------------------------------------------

    # Base numbers are tuned so that at Normal font (11 pt → fontScale 1.0):
    #   • Watchlist shows section title + ≥ 3 rows + add/remove buttons.
    #   • Goal Dashboard + Analytics Panel both fit their hero + metrics.
    #   • Holdings and Trades each show ≥ 3 body rows below their header.
    # Other font sizes scale linearly (Large × 1.18, X-Large × 1.45, etc.).
    _BASE_MIN_WIDTH = 900
    _BASE_MIN_HEIGHT = 860

    def _current_font_scale(self) -> float:
        try:
            from .theme import FONT_SIZES as _FS
            return float(_FS.get(self.theme.font_size_label, 11)) / 11.0
        except Exception:
            return 1.0

    def _apply_minimum_window_size(self) -> None:
        scale = self._current_font_scale()
        w = int(self._BASE_MIN_WIDTH * scale)
        h = int(self._BASE_MIN_HEIGHT * scale)
        self.setMinimumSize(w, h)
        # If the window is already smaller than the new minimum (e.g. user
        # just picked X-Large font), enlarge it so all content fits.
        cur = self.size()
        if cur.width() < w or cur.height() < h:
            self.resize(max(cur.width(), w), max(cur.height(), h))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _qsettings(self) -> QSettings:
        return QSettings(self.ORG, self.APP)

    def _all_trades(self) -> List[Trade]:
        try:
            return list(self._store.get_all_trades())
        except Exception:
            return []

    def _account_trades(self, account_name: str, all_trades: List[Trade]) -> List[Trade]:
        return [t for t in all_trades if (t.account or "").strip() == account_name]

    def _save_account(self, account_name: str, trades: List[Trade]) -> None:
        try:
            self._store.save_account_trades(account_name, trades)
        except Exception as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))
            return
        self._app.refresh_all_accounts()

    def _safe_run(self, fn, *args, **kwargs) -> None:
        """Run `fn` on the next event-loop iteration, catching any exception.

        Used by QML-triggered slots that open modal dialogs or context menus.
        Deferring via QTimer.singleShot(0, …) lets the QML callback unwind
        before the dialog opens — without this, the nested event loops
        (QML render → Qt slot → QMenu.exec → QDialog.exec) can crash on
        Windows when the QQuickWidget tries to repaint between them.
        """

        def _wrap():
            try:
                fn(*args, **kwargs)
            except Exception as exc:
                get_logger("ui").exception("dialog/menu handler failed")
                try:
                    QMessageBox.warning(self, "Error", str(exc))
                except Exception:
                    pass

        QTimer.singleShot(0, _wrap)

    def _trade_default_quantity(self) -> int:
        try:
            return max(1, int(self._qsettings().value("trade_defaults/default_quantity", 1) or 1))
        except Exception:
            return 1

    def _trade_quantity_increment(self) -> int:
        try:
            return max(1, int(self._qsettings().value("trade_defaults/quantity_increment", 1) or 1))
        except Exception:
            return 1

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_settings = file_menu.addAction("Settings")
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._open_settings_dialog)
        file_menu.addAction("User Account").triggered.connect(self._open_user_account_dialog)
        file_menu.addSeparator()
        file_menu.addAction("Check for Updates…").triggered.connect(self._check_for_updates)
        file_menu.addSeparator()
        file_menu.addAction("Quit").triggered.connect(self.close)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction("Trade History Settings").triggered.connect(self._on_open_trade_history_options)
        view_menu.addAction("Goal Dashboard Options").triggered.connect(self._on_open_goal_options)

        admin_menu = self.menuBar().addMenu("&Admin")
        self.act_view_user_portfolio = admin_menu.addAction("View User Portfolio…")
        self.act_view_user_portfolio.triggered.connect(self._open_view_user_portfolio)
        self.act_view_user_portfolio.setVisible(self._store.is_admin)

        # F5 refresh shortcut (works anywhere in the window).
        act = QAction("Refresh Marks (F5)", self)
        act.setShortcut(QKeySequence("F5"))
        act.triggered.connect(self._level1_tick)
        self.addAction(act)

    def _build_status_corner(self) -> None:
        self.spinner = SpinnerLabel()
        self.spinner.setFixedWidth(14)
        self.lbl_updating = QLabel("")
        self.lbl_status = QLabel("")
        self.lbl_updating.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_updating.setMinimumWidth(86)
        self.lbl_status.setMinimumWidth(172)
        self.lbl_updating.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(120)
        self.progress.setVisible(False)

        status_corner = QWidget(self)
        status_corner.setObjectName("menuStatusCorner")
        sr = QHBoxLayout(status_corner)
        sr.setContentsMargins(8, 2, 8, 3);
        sr.setSpacing(8)
        self.lbl_updating.setObjectName("menuUpdatingLabel")
        self.lbl_status.setObjectName("menuOnlineLabel")
        sr.addWidget(self.spinner);
        sr.addWidget(self.lbl_updating)
        sr.addWidget(self.lbl_status);
        sr.addWidget(self.progress)
        status_corner.adjustSize()
        self.menuBar().setCornerWidget(status_corner, Qt.Corner.TopRightCorner)
        self.statusBar().hide()

    def _build_qml_host(self) -> None:
        self.qml_widget = QQuickWidget()
        self.qml_widget.engine().rootContext().setContextProperty("app", self._app)
        self.qml_widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        # Make the QQuickWidget see-through so the QMainWindow palette shows
        # at the borders during a resize (no white flicker).
        self.qml_widget.setClearColor(QColor(0, 0, 0, 0))

        qml_main = _QML_DIR / "Main.qml"
        self.qml_widget.setSource(QUrl.fromLocalFile(str(qml_main)))

        if self.qml_widget.status() == QQuickWidget.Status.Error:
            errors = "\n".join(str(e) for e in self.qml_widget.errors())
            get_logger("qml").error("QML failed to load:\n%s", errors)

        self.setCentralWidget(self.qml_widget)

    # ------------------------------------------------------------------
    # Watchlist persistence + slots wired from QML
    # ------------------------------------------------------------------

    def _load_watchlist(self) -> None:
        try:
            symbols = self._store.get_watchlist()
        except Exception:
            symbols = []
        if not symbols:
            raw = self._qsettings().value("watchlist/items", [])
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = []
            if isinstance(raw, list) and raw:
                symbols = [str(t).upper() for t in raw if str(t).strip()]
            if not symbols:
                symbols = list(self.DEFAULT_WATCHLIST)
        self._app.set_watchlist([str(s).upper() for s in symbols])

    def _save_watchlist(self) -> None:
        symbols = self._app.watchlist_symbols()
        try:
            self._store.save_watchlist(symbols)
        except Exception:
            pass
        s = self._qsettings()
        s.setValue("watchlist/items", symbols)
        s.sync()

    def _on_add_ticker(self) -> None:
        text, ok = QInputDialog.getText(self, "Add ticker", "Symbol:")
        if not ok or not text.strip():
            return
        sym = text.strip().upper()
        if not all(ch.isalnum() or ch in ".-" for ch in sym):
            QMessageBox.warning(self, "Invalid symbol", "Use letters, numbers, dot or dash only.")
            return
        symbols = self._app.watchlist_symbols()
        if sym in symbols:
            return
        symbols.append(sym)
        self._app.set_watchlist(symbols)
        self._save_watchlist()
        self._level1_tick()

    def _on_remove_ticker(self, row: int) -> None:
        symbols = self._app.watchlist_symbols()
        if not (0 <= row < len(symbols)):
            return
        sym = symbols[row]
        if QMessageBox.question(self, "Remove", f"Remove {sym} from watchlist?") \
                != QMessageBox.StandardButton.Yes:
            return
        del symbols[row]
        self._app.set_watchlist(symbols)
        self._save_watchlist()

    def _on_rename_ticker(self, row: int, new_symbol: str) -> None:
        symbols = self._app.watchlist_symbols()
        if not (0 <= row < len(symbols)):
            return
        sym = (new_symbol or "").strip().upper()
        if not sym or not all(ch.isalnum() or ch in ".-" for ch in sym):
            QMessageBox.warning(self, "Invalid symbol", "Use letters, numbers, dot or dash only.")
            return
        if sym in symbols:
            QMessageBox.information(self, "Duplicate", f"{sym} is already in the list.")
            return
        symbols[row] = sym
        self._app.set_watchlist(symbols)
        self._save_watchlist()

    # ------------------------------------------------------------------
    # Trade CRUD slots wired from QML
    # ------------------------------------------------------------------

    def _on_add_trade(self) -> None:
        account = self._app.currentAccount
        if account is None:
            return
        dlg = TradeEditDialog(
            watchlist_symbols=self._app.watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        trade = dlg.to_trade()
        trade.account = account.name
        all_trades = self._all_trades()
        all_trades.append(trade)
        self._save_account(account.name, self._account_trades(account.name, all_trades))

    def _on_edit_trade(self, source_index: int) -> None:
        account = self._app.currentAccount
        if account is None:
            return
        account_trades = self._account_trades(account.name, self._all_trades())
        if not (0 <= source_index < len(account_trades)):
            return
        trade = account_trades[source_index]
        dlg = TradeEditDialog(
            trade,
            watchlist_symbols=self._app.watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.to_trade()
        updated.account = (trade.account or account.name).strip() or account.name
        account_trades[source_index] = updated
        self._save_account(updated.account, account_trades)

    def _on_delete_trade(self, source_index: int) -> None:
        account = self._app.currentAccount
        if account is None:
            return
        account_trades = self._account_trades(account.name, self._all_trades())
        if not (0 <= source_index < len(account_trades)):
            return
        trade = account_trades[source_index]
        if QMessageBox.question(
                self, "Delete trade",
                f"Delete {trade.normalized_instrument()} trade for {trade.share_count:,d} shares?",
        ) != QMessageBox.StandardButton.Yes:
            return
        del account_trades[source_index]
        self._save_account(account.name, account_trades)

    def _on_set_goal_target(self, value: float) -> None:
        account = self._app.currentAccount
        if account is None:
            return
        try:
            shared, _ = self._store.get_goal_group()
            shared_set = set(shared)
        except Exception:
            shared_set = set()
        try:
            if account.name in shared_set:
                for name in shared_set:
                    self._store.set_goal_target(name, float(value))
            else:
                self._store.set_goal_target(account.name, float(value))
        except Exception as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))
            return
        self._app.refresh_all_accounts()

    # ------------------------------------------------------------------
    # Goal options dialog
    # ------------------------------------------------------------------

    def _on_open_goal_options(self) -> None:
        try:
            accounts = self._store.get_account_names()
            shared_names, _shared_goal = self._store.get_goal_group()
        except Exception:
            return
        goal_targets: Dict[str, float] = {}
        preset_values: Dict[str, List[float]] = {}
        for a in accounts:
            try:
                goal_targets[a] = self._store.get_goal_target(a)
                preset_values[a] = self._store.get_goal_presets(a)
            except Exception:
                goal_targets[a] = 500_000.0
                preset_values[a] = [250_000.0, 500_000.0, 1_000_000.0]
        dlg = GoalDashboardOptionsDialog(accounts, shared_names, goal_targets, preset_values, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._store.set_goal_group(
                dlg.selected_accounts(),
                dlg.shared_goal(),
                dlg.individual_goals(),
                dlg.all_preset_values(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))
            return
        self._app.refresh_all_accounts()

    def _on_open_trade_history_options(self) -> None:
        QMessageBox.information(
            self, "Trade History Settings",
            "In the new view, the Trade History columns are fixed and "
            "sorting is via header click.\n\n"
            "Use the filter box and the status dropdown to narrow the rows.",
        )

    # ------------------------------------------------------------------
    # Context menus driven by QML right-clicks
    # ------------------------------------------------------------------

    def _on_holdings_menu(self, instrument: str) -> None:
        account = self._app.currentAccount
        if account is None or not instrument:
            return
        account_trades = self._account_trades(account.name, self._all_trades())
        open_long = [t for t in account_trades
                     if not t.is_closed and not t.is_pending and not t.is_short
                     and t.normalized_instrument() == instrument]
        open_short = [t for t in account_trades
                      if not t.is_closed and not t.is_pending and t.is_short
                      and t.normalized_instrument() == instrument]
        if not open_long and not open_short:
            return
        is_short = bool(open_short) and not open_long

        menu = QMenu(self)
        # All action handlers are deferred via _safe_run so the dialog they
        # open is created in a fresh event-loop tick AFTER the QMenu's exec
        # loop has fully unwound. Opening a QDialog directly from a QMenu
        # action lambda triggers a 3-deep nested event loop (QML → menu →
        # dialog) which crashes intermittently on Windows.
        if is_short:
            menu.addAction("Buy to Cover").triggered.connect(
                lambda: self._safe_run(self._close_position, instrument, account.name, account_trades, True))
        else:
            menu.addAction("Close Holdings").triggered.connect(
                lambda: self._safe_run(self._close_position, instrument, account.name, account_trades, False))
            menu.addAction("Mark Down").triggered.connect(
                lambda: self._safe_run(self._mark_down, instrument, account.name, account_trades))
            menu.addAction("Double Down").triggered.connect(
                lambda: self._safe_run(self._double_down, instrument, account.name, account_trades))
        menu.exec(QCursor.pos())

    def _close_position(self, instrument: str, account_name: str,
                        account_trades: List[Trade], is_short: bool) -> None:
        matching = [t for t in account_trades
                    if not t.is_closed and not t.is_pending
                    and t.is_short == is_short
                    and t.normalized_instrument() == instrument]
        if not matching:
            return
        total_qty = sum(int(t.share_count) for t in matching)
        total_cost = sum(float(t.buy_price) * int(t.share_count) for t in matching)
        oldest = min((t.open_date for t in matching if t.open_date), default=date.today())
        notes = " | ".join(t.notes for t in matching if t.notes)
        avg_cost = (total_cost / total_qty) if total_qty > 0 else 0.0
        combined = Trade(
            instrument=instrument, share_count=total_qty, buy_price=avg_cost,
            sell_price=None, open_date=oldest, close_date=None, notes=notes,
            is_short=is_short,
        )
        dlg = TradeEditDialog(
            trade=combined, watchlist_symbols=self._app.watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            close_holdings_mode=not is_short,
            cover_mode=is_short,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        closing = dlg.to_trade()
        if closing.sell_price is None or closing.close_date is None:
            return
        for t in matching:
            t.sell_price = float(closing.sell_price)
            t.close_date = closing.close_date
        self._save_account(account_name, account_trades)

    def _mark_down(self, instrument: str, account_name: str,
                   account_trades: List[Trade]) -> None:
        matching = [t for t in account_trades
                    if not t.is_closed and not t.is_pending and not t.is_short
                    and t.normalized_instrument() == instrument]
        if not matching:
            return
        total_qty = sum(int(t.share_count) for t in matching)
        total_cost = sum(float(t.buy_price) * int(t.share_count) for t in matching)
        if total_qty <= 0:
            return
        holding = Holding(instrument=instrument, qty=total_qty,
                          avg_cost=total_cost / total_qty, notes="")
        dlg = MarkDownDialog(
            holding=holding,
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        trade = dlg.to_trade()
        trade.account = account_name
        account_trades.append(trade)
        self._save_account(account_name, account_trades)

    def _double_down(self, instrument: str, account_name: str,
                     account_trades: List[Trade]) -> None:
        matching = [t for t in account_trades
                    if not t.is_closed and not t.is_pending and not t.is_short
                    and t.normalized_instrument() == instrument]
        if not matching:
            return
        total_qty = sum(int(t.share_count) for t in matching)
        total_cost = sum(float(t.buy_price) * int(t.share_count) for t in matching)
        if total_qty <= 0:
            return
        holding = Holding(instrument=instrument, qty=total_qty,
                          avg_cost=total_cost / total_qty, notes="")
        marks = self._app._marks_by_symbol.get(instrument, {})
        current_mark = float(marks["price"]) if marks.get("price") is not None else None
        dlg = DoubleDownDialog(
            holding=holding, current_mark=current_mark,
            quantity_increment=self._trade_quantity_increment(), parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        trade = dlg.to_trade()
        trade.account = account_name
        account_trades.append(trade)
        self._save_account(account_name, account_trades)

    def _on_trade_menu(self, source_index: int) -> None:
        account = self._app.currentAccount
        if account is None:
            return
        account_trades = self._account_trades(account.name, self._all_trades())
        if not (0 <= source_index < len(account_trades)):
            return
        trade = account_trades[source_index]
        menu = QMenu(self)
        # Defer dialog opens via _safe_run — see _on_holdings_menu for why.
        if trade.is_pending:
            menu.addAction("Mark as Fulfilled").triggered.connect(
                lambda: self._safe_run(self._fulfill_pending, source_index))
            menu.addSeparator()
        menu.addAction("Edit Trade").triggered.connect(
            lambda: self._safe_run(self._on_edit_trade, source_index))
        menu.addAction("Delete Trade").triggered.connect(
            lambda: self._safe_run(self._on_delete_trade, source_index))
        menu.exec(QCursor.pos())

    def _fulfill_pending(self, source_index: int) -> None:
        account = self._app.currentAccount
        if account is None:
            return
        account_trades = self._account_trades(account.name, self._all_trades())
        if not (0 <= source_index < len(account_trades)):
            return
        trade = account_trades[source_index]
        if not trade.is_pending:
            QMessageBox.information(self, "Not pending", "This trade is not a pending order.")
            return
        dlg = FulfillOrderDialog(trade, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        trade.is_pending = False
        trade.open_date = dlg.get_fill_date()
        trade.buy_price = dlg.get_fill_price()
        self._save_account(account.name, account_trades)

    # ------------------------------------------------------------------
    # Settings / updates / user account dialogs
    # ------------------------------------------------------------------

    def _open_settings_dialog(self) -> None:
        from .settings_dialog import SettingsDialog
        s = self._qsettings()
        cv = {
            "L1_INTERVAL": self.L1_INTERVAL, "NET_INTERVAL": self.NET_INTERVAL,
            "L1_ENABLED": self.L1_ENABLED,
            "THEME_OVERRIDE": s.value("ui/THEME_OVERRIDE", getattr(self.theme, "override_mode", "System")),
            "MATCH_SYSTEM_ACCENT": s.value("ui/MATCH_SYSTEM_ACCENT",
                                            getattr(self.theme, "match_system_accent", True), type=bool),
            "THEME_NAME": s.value("ui/THEME_NAME", getattr(self.theme, "theme_name", "Default")),
            "FONT_SIZE": s.value("ui/FONT_SIZE", getattr(self.theme, "font_size_label", "Normal")),
            "TRADE_DEFAULT_QUANTITY": int(s.value("trade_defaults/default_quantity", 1) or 1),
            "TRADE_QUANTITY_INCREMENT": int(s.value("trade_defaults/quantity_increment", 1) or 1),
        }
        dlg = SettingsDialog(self, s, cv)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.get_values()
        self.L1_INTERVAL = int(vals["L1_INTERVAL"])
        self.NET_INTERVAL = int(vals["NET_INTERVAL"])
        self.L1_ENABLED = bool(vals["L1_ENABLED"])
        self.theme.set_override_mode(vals["THEME_OVERRIDE"])
        self.theme.set_match_system_accent(vals["MATCH_SYSTEM_ACCENT"])
        self.theme.set_theme(vals.get("THEME_NAME", "Default"))
        self.theme.set_font_size(vals.get("FONT_SIZE", "Normal"))
        s.setValue("ui/THEME_OVERRIDE", self.theme.override_mode)
        s.setValue("ui/MATCH_SYSTEM_ACCENT", self.theme.match_system_accent)
        s.setValue("ui/THEME_NAME", self.theme.theme_name)
        s.setValue("ui/FONT_SIZE", self.theme.font_size_label)
        s.setValue("trade_defaults/default_quantity", int(vals["TRADE_DEFAULT_QUANTITY"]))
        s.setValue("trade_defaults/quantity_increment", int(vals["TRADE_QUANTITY_INCREMENT"]))
        s.sync()
        self.timer_l1.setInterval(self.L1_INTERVAL)
        self.timer_net.setInterval(self.NET_INTERVAL)
        self.timer_l1.start() if self.L1_ENABLED else self.timer_l1.stop()

    def _check_for_updates(self) -> None:
        from .update_checker import check_for_updates
        check_for_updates(parent=self, silent_if_current=False)

    def _open_user_account_dialog(self) -> None:
        UserAccountDialog(self._store, self).exec()
        # Account list may have changed.
        self._app.rebuild_accounts()
        self._app.refresh_all_accounts()

    def _open_view_user_portfolio(self) -> None:
        if not self._store.is_admin:
            QMessageBox.information(self, "Admin Only",
                                    "Only admin accounts can view other users' portfolios.")
            return
        _remote_ok = (
            isinstance(self._store, RemoteDataStore) or
            (isinstance(self._store, FallbackDataStore) and self._store._is_online)
        )
        if not _remote_ok:
            QMessageBox.information(
                self, "Server Required",
                "Viewing other users requires a server connection. "
                "The app is currently in offline mode — reconnect first.",
            )
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
        if user_id in self._viewer_windows:
            w = self._viewer_windows[user_id]
            w.raise_(); w.activateWindow(); return
        user_store = self._store.store_for_user(user_id, user["username"])
        viewer = UserPortfolioViewer(user_store, user["username"], self._qsettings(), parent=None)
        viewer.closed.connect(lambda uid=user_id: self._viewer_windows.pop(uid, None))
        self._viewer_windows[user_id] = viewer
        viewer.show()

    # ------------------------------------------------------------------
    # Background timers + worker threads
    # ------------------------------------------------------------------

    def _init_timers(self) -> None:
        self.timer_l1 = QTimer(self)
        self.timer_l1.setInterval(self.L1_INTERVAL)
        self.timer_l1.timeout.connect(self._level1_tick)
        self.timer_net = QTimer(self)
        self.timer_net.setInterval(self.NET_INTERVAL)
        self.timer_net.timeout.connect(self._kick_netcheck)
        self.timer_l1.start() if self.L1_ENABLED else self.timer_l1.stop()
        self.timer_net.start()
        # Defer first tick — avoids spawning a QThread before the QML scene
        # has finished mounting (Windows access-violation guard).
        QTimer.singleShot(250, self._kick_netcheck)
        QTimer.singleShot(500, self._level1_tick)

    def _thread_running(self, thread: Optional[QThread]) -> bool:
        return thread is not None and thread.isRunning()

    def _busy_enter(self) -> None:
        self._busy_ops += 1
        if self._busy_ops == 1:
            self.spinner.start(90);
            self.lbl_updating.setText("Updating...")

    def _busy_leave(self) -> None:
        self._busy_ops = max(0, self._busy_ops - 1)
        if self._busy_ops == 0:
            self.spinner.stop();
            self.lbl_updating.setText("")

    def _level1_tick(self) -> None:
        if self._closing or self._thread_running(self._marks_thread):
            return
        # Watchlist + every account's open holdings.
        tickers = list(self._app.watchlist_symbols())
        for account in self._app.accounts:
            try:
                for h in account.holdings._rows:
                    sym = h.get("instrument")
                    if sym and sym not in tickers:
                        tickers.append(sym)
            except Exception:
                pass
        tickers = [t for t in dict.fromkeys(tickers) if t]
        if not tickers:
            return
        self._busy_enter()
        worker = MarksWorker(tickers)
        thread = QThread(self)
        self._marks_worker = worker
        self._marks_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_marks)
        worker.error.connect(self._on_marks_error)
        worker.done.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_marks_thread)
        thread.start()

    def _cleanup_marks_thread(self) -> None:
        self._marks_thread = None
        self._marks_worker = None
        if not self._closing:
            self._busy_leave()

    def _on_marks(self, data: dict) -> None:
        if self._closing:
            return
        self._app.apply_marks(data)

    def _on_marks_error(self, _msg: str) -> None:
        if self._closing:
            return
        self.lbl_status.setText("● Offline")
        self.lbl_status.setStyleSheet("color: #ef4444;")

    def _kick_netcheck(self) -> None:
        if self._closing or self._thread_running(self._netcheck_thread):
            return
        worker = NetCheckWorker()
        thread = QThread(self)
        self._netcheck_worker = worker
        self._netcheck_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_net_status)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_netcheck_thread)
        thread.start()

    def _cleanup_netcheck_thread(self) -> None:
        self._netcheck_thread = None
        self._netcheck_worker = None

    def _on_net_status(self, ok: bool) -> None:
        if self._closing:
            return
        self._online = ok
        if not ok:
            self.lbl_status.setText("● Offline")
            self.lbl_status.setStyleSheet("color: #ef4444;")
        elif isinstance(self._store, FallbackDataStore) and not self._store._is_online:
            n = self._store.pending_sync_count
            suffix = f" — {n} change{'s' if n != 1 else ''} queued" if n else " — server unreachable"
            self.lbl_status.setText(f"● Online{suffix}")
            self.lbl_status.setStyleSheet("color: #f59e0b;")
        elif not isinstance(self._store, (RemoteDataStore, FallbackDataStore)):
            self.lbl_status.setText("● Online — working offline")
            self.lbl_status.setStyleSheet("color: #f59e0b;")
        else:
            self.lbl_status.setText("● Online")
            self.lbl_status.setStyleSheet("color: #22c55e;")

    def _init_reconnect_timer(self) -> None:
        if not isinstance(self._store, FallbackDataStore):
            return
        self._reconnect_timer_obj = QTimer(self)
        self._reconnect_timer_obj.setInterval(30_000)
        self._reconnect_timer_obj.timeout.connect(self._attempt_reconnect)
        self._reconnect_timer_obj.start()

    def _attempt_reconnect(self) -> None:
        if not isinstance(self._store, FallbackDataStore):
            return
        if self._closing or self._store._is_online or self._thread_running(self._reconnect_thread):
            return
        serial_debug("Attempting reconnect to server...")
        worker = ReconnectWorker(self._store)
        thread = QThread(self)
        self._reconnect_worker = worker
        self._reconnect_thread = thread
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_reconnect_finished)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_reconnect_thread)
        thread.start()

    def _cleanup_reconnect_thread(self) -> None:
        self._reconnect_thread = None
        self._reconnect_worker = None

    def _on_reconnect_finished(self, ok: bool) -> None:
        if ok and not self._closing:
            self._on_reconnected()

    def _on_reconnected(self) -> None:
        if self._closing:
            return
        pending = self._store.pending_sync_count
        if pending == 0:
            self.lbl_status.setText("● Online")
        else:
            self.lbl_status.setText("● Online — syncing...")
        self.lbl_status.setStyleSheet("color: #22c55e;")
        self._app.refresh_all_accounts()

    def _set_offline_status(self, n_pending: int) -> None:
        self.lbl_status.setText(f"● Offline — {n_pending} change{'s' if n_pending != 1 else ''} queued")
        self.lbl_status.setStyleSheet("color: #f59e0b;")

    def _set_synced_status(self, synced_count: int) -> None:
        if synced_count > 0:
            self.lbl_status.setText(f"● Online — synced {synced_count} change{'s' if synced_count != 1 else ''}")
        else:
            self.lbl_status.setText("● Online")
        self.lbl_status.setStyleSheet("color: #22c55e;")

    # ------------------------------------------------------------------
    # Save / close
    # ------------------------------------------------------------------

    def _save_settings(self) -> None:
        s = self._qsettings()
        symbols = self._app.watchlist_symbols()
        try:
            self._store.save_watchlist(symbols)
        except Exception:
            pass
        s.setValue("watchlist/items", symbols)
        s.setValue("intervals/L1_INTERVAL", self.L1_INTERVAL)
        s.setValue("intervals/NET_INTERVAL", self.NET_INTERVAL)
        s.setValue("intervals/L1_ENABLED", self.L1_ENABLED)
        s.setValue("ui/THEME_OVERRIDE", self.theme.override_mode)
        s.setValue("ui/MATCH_SYSTEM_ACCENT", self.theme.match_system_accent)
        s.setValue("ui/THEME_NAME", self.theme.theme_name)
        s.setValue("ui/FONT_SIZE", self.theme.font_size_label)
        s.sync()

    def closeEvent(self, event):
        self._closing = True
        self._save_settings()
        try:
            self.theme.stop_watching()
        except Exception:
            pass

        for timer_name in ("timer_l1", "timer_net", "_reconnect_timer_obj"):
            timer = getattr(self, timer_name, None)
            if timer is None:
                continue
            timer.stop()
            try:
                timer.timeout.disconnect()
            except Exception:
                pass

        for viewer in list(self._viewer_windows.values()):
            try:
                viewer.close()
            except Exception:
                pass

        for thread_name in ("_marks_thread", "_netcheck_thread", "_reconnect_thread"):
            thread = getattr(self, thread_name, None)
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(4000)
            except Exception:
                pass

        self._marks_thread = None;
        self._marks_worker = None
        self._netcheck_thread = None;
        self._netcheck_worker = None
        self._reconnect_thread = None;
        self._reconnect_worker = None
        super().closeEvent(event)
