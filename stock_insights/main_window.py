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

# Importing QtCharts here is required even though we don't reference any
# of its Python symbols — the import is what registers the `QtCharts`
# QML module (ChartView, LineSeries, DateTimeAxis, ValueAxis used by
# EquityCurveCard.qml). Without it the QML engine silently fails to
# instantiate ChartView and the curve renders as a blank area.
from PySide6 import QtCharts  # noqa: F401  (side-effect import)
from PySide6.QtCore import Qt, QSettings, QTimer, QThread, QUrl
from PySide6.QtGui import QAction, QColor, QCursor, QKeySequence
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QWidget,
)

from .admin_dialogs import (
    ManageUserPasswordsDialog,
    SelectUserDialog,
    UserAccountDialog,
    UserPortfolioViewer,
)
from .api_client import DataStore, FallbackDataStore, RemoteDataStore
from .logging_utils import get_logger, setup_logging, serial_debug
from .portfolio import Holding, Trade
from .portfolio_tab import (
    DoubleDownDialog,
    FulfillOrderDialog,
    GoalDashboardOptionsDialog,
    MarkDownDialog,
    TradeEditDialog,
)
from .qml_bridge import AppController
from .theme import ThemeManager
from .widgets import SpinnerLabel
from .workers import MarksWorker, NetCheckWorker, ReconnectWorker

_ORG = "StockInsights"
_APP = "StocksGUI"
_QML_DIR = Path(__file__).resolve().parent / "qml"


# Admin/dialog classes that used to live in this file (UserAccountDialog,
# UserPortfolioViewer, SelectUserDialog, ManageUserPasswordsDialog) were
# extracted to admin_dialogs.py during the T4.12 split — that shaved
# ~450 lines off this module without changing any external API.
# Per-symbol drill-down lives in symbol_history_dialog.py for the same
# reason: it's a standalone QDialog and doesn't need MainWindow internals.


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
        # Apply view-menu preferences (e.g. "Hide Equity Curve") before
        # QML mounts so the affected cards don't briefly flash visible
        # then collapse. Default is "shown" if no setting saved yet.
        self._app.set_equity_curve_visible(
            s.value("view/EQUITY_CURVE_VISIBLE", True, type=bool)
        )
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

        # Safety net — defer a launch snapshot to ~/.stock_insights/auto_backups/
        # to QTimer so it runs after the UI is up (doesn't block startup).
        # Prunes to the last AUTO_BACKUP_KEEP files automatically, so even
        # 100 launches doesn't fill the home directory. Best-effort: a
        # disk-full / permission failure here is silently swallowed.
        QTimer.singleShot(0, self._write_launch_snapshot)

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
    #   • Equity Curve renders without the chart collapsing.
    #   • Holdings and Trades each show ≥ 3 body rows below their header.
    # Other font sizes scale linearly (Large × 1.18, X-Large × 1.45, etc.).
    _BASE_MIN_WIDTH = 900
    # Vertical budget at Normal font, summed top → bottom:
    #   menubar (~26) + SplitView margins (20) + PortfolioPane tab bar
    #   (42) + PortfolioView margins (24) + sum of card minimums
    #   [270 + 210 + 220 + 300] + 3× layout spacing (36) = ~1148.
    # 1170 leaves ~22 px of slack for font-metric variation and the
    # window decoration line drawn just above the menubar on some Qt
    # styles. (Top-row min was 260, now 270 after the Drawdown row was
    # added to AnalyticsPanel.)
    _BASE_MIN_HEIGHT = 1170
    # Drop when the user hides the equity curve (View menu →
    # "Hide Equity Curve"). The curve contributes 210 px of card
    # minimum + 12 px of ColumnLayout spacing = 222 px reclaimed.
    _EQUITY_CURVE_HEIGHT_COST = 222

    def _current_font_scale(self) -> float:
        try:
            from .theme import FONT_SIZES as _FS
            return float(_FS.get(self.theme.font_size_label, 11)) / 11.0
        except Exception:
            return 1.0

    def _apply_minimum_window_size(self) -> None:
        scale = self._current_font_scale()
        w = int(self._BASE_MIN_WIDTH * scale)
        base_h = self._BASE_MIN_HEIGHT
        # When the equity curve is hidden, the layout no longer reserves
        # its slot — let the user shrink the window accordingly. We only
        # rely on _app being set; this runs after AppController init.
        if hasattr(self, "_app") and not self._app.equityCurveVisible:
            base_h -= self._EQUITY_CURVE_HEIGHT_COST
        h = int(base_h * scale)
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
        """Persist a slice of trades for one account, then refresh the UI.

        Backgrounded via `_run_in_background` so the calling dialog can
        close immediately on slow networks instead of freezing for the
        HTTP roundtrip. The local in-memory `_app.refresh_all_accounts()`
        runs on the GUI thread once the network write returns.
        """
        self._run_in_background(
            self._store.save_account_trades,
            args=(account_name, list(trades)),
            on_done=lambda _result: self._app.refresh_all_accounts(),
            on_error=lambda msg: QMessageBox.warning(self, "Save Failed", msg),
            label=f"save_account_trades({account_name})",
        )

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

    def _run_in_background(self, fn, args=(), kwargs=None,
                           on_done=None, on_error=None,
                           label: str = "store-call") -> None:
        """Run `fn(*args, **kwargs)` in a background QThread, then
        invoke `on_done(result)` (or `on_error(msg)`) on the GUI thread.

        Use this for any potentially-blocking operation triggered by a
        UI action — `save_account_trades` over the network, watchlist
        writes, etc. — so the UI stays responsive on slow links.

        Lifecycle: a fresh QThread + StoreCallWorker pair is created
        per call, started, and torn down on completion. Both are
        parented to `self` and tracked in `_active_workers` to keep
        them alive past the function return (Python GC otherwise reaps
        the references mid-call and SEGVs on exit).

        Don't use this for ops that need to BLOCK (e.g. data needed to
        render the next paint). Use it for fire-and-update flows.
        """
        from .workers import StoreCallWorker
        thread = QThread(self)
        worker = StoreCallWorker(fn, args=args, kwargs=kwargs or {}, label=label)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        # Track the worker pair so they survive past this method's
        # return — the Python ref count is what keeps QObjects alive,
        # and without this they'd be collected before the thread runs.
        if not hasattr(self, "_active_workers"):
            self._active_workers = []
        self._active_workers.append((thread, worker))

        def _on_done(result):
            try:
                if on_done is not None:
                    on_done(result)
            finally:
                _cleanup()

        def _on_error(msg):
            try:
                if on_error is not None:
                    on_error(msg)
            finally:
                _cleanup()

        def _cleanup():
            thread.quit()
            thread.wait(50)  # short wait — run() returned already
            try:
                self._active_workers.remove((thread, worker))
            except ValueError:
                pass
            worker.deleteLater()
            thread.deleteLater()

        worker.done.connect(_on_done)
        worker.error.connect(_on_error)
        thread.start()

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

        # ── Export / Backup ──────────────────────────────────────────────
        act_export = file_menu.addAction("Export Trades to CSV…")
        act_export.setShortcut("Ctrl+E")
        act_export.triggered.connect(lambda: self._safe_run(self._on_export_csv))

        act_backup = file_menu.addAction("Backup All Data…")
        act_backup.triggered.connect(lambda: self._safe_run(self._on_backup))

        act_restore = file_menu.addAction("Restore From Backup…")
        act_restore.triggered.connect(lambda: self._safe_run(self._on_restore))

        file_menu.addSeparator()
        file_menu.addAction("Check for Updates…").triggered.connect(self._check_for_updates)
        file_menu.addSeparator()
        file_menu.addAction("Quit").triggered.connect(self.close)

        view_menu = self.menuBar().addMenu("&View")

        # Checkable toggle — checked = curve hidden, unchecked = visible.
        # The label reads as the action the user is performing ("Hide
        # Equity Curve"), so when the box is ticked the curve disappears
        # and the menu item still says "Hide Equity Curve" (now ticked,
        # indicating the hide is in effect). Unchecking re-shows it.
        self.act_hide_equity_curve = QAction("Hide Equity Curve", self)
        self.act_hide_equity_curve.setCheckable(True)
        self.act_hide_equity_curve.setChecked(not self._app.equityCurveVisible)
        self.act_hide_equity_curve.toggled.connect(self._on_toggle_hide_equity_curve)
        view_menu.addAction(self.act_hide_equity_curve)
        view_menu.addSeparator()

        view_menu.addAction("Trade History Settings").triggered.connect(self._on_open_trade_history_options)
        view_menu.addAction("Goal Dashboard Options").triggered.connect(self._on_open_goal_options)

        admin_menu = self.menuBar().addMenu("&Admin")
        self.act_view_user_portfolio = admin_menu.addAction("View User Portfolio…")
        self.act_view_user_portfolio.triggered.connect(self._open_view_user_portfolio)
        self.act_view_user_portfolio.setVisible(self._store.is_admin)

        self.act_manage_passwords = admin_menu.addAction("Manage User Passwords…")
        self.act_manage_passwords.triggered.connect(
            lambda: self._safe_run(self._open_manage_passwords))
        self.act_manage_passwords.setVisible(self._store.is_admin)

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
        """Persist the watchlist remotely (best-effort) + locally.

        The remote write is backgrounded so the UI doesn't lag when the
        user adds or removes a ticker on a slow network. Local QSettings
        write stays sync — it's a microsecond op against a local file
        and we want it durable before the function returns so a crash
        doesn't lose the change.
        """
        symbols = self._app.watchlist_symbols()
        # Remote: background, swallow errors (matches old behavior — the
        # local QSettings copy is the durable record).
        self._run_in_background(
            self._store.save_watchlist,
            args=(list(symbols),),
            on_error=lambda msg: None,
            label="save_watchlist",
        )
        # Local: synchronous, durable before we return.
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

    def _on_move_trade(self, source_index: int, destination_account: str) -> None:
        """Move a single trade from the current portfolio to another portfolio
        within the same user. Triggered from the trade-history right-click menu.

        The data store has no atomic multi-account write, so this does two
        sequential `save_account_trades` calls — source first, then
        destination. That order is important: if we saved destination first,
        `LocalDataStore.save_account_trades` would still see the moved trade
        on disk under its old account, leave it in `kept`, and then the new
        save would add a second copy under the destination account, leaving
        the trade duplicated.

        For FallbackDataStore users, both writes go through the offline sync
        queue, so a remote failure mid-move is recovered the next time the
        server is reachable.
        """
        account = self._app.currentAccount
        if account is None or destination_account == account.name:
            return
        all_trades = self._all_trades()
        src_trades = self._account_trades(account.name, all_trades)
        if not (0 <= source_index < len(src_trades)):
            return
        moved = src_trades[source_index]

        if QMessageBox.question(
                self, "Move Trade",
                f"Move <b>{moved.normalized_instrument()}</b> "
                f"({moved.share_count:,d} shares) from "
                f"<b>{account.name}</b> to <b>{destination_account}</b>?",
        ) != QMessageBox.StandardButton.Yes:
            return

        # IMPORTANT: compute the destination slice BEFORE mutating
        # moved.account, otherwise `_account_trades(destination, ...)` would
        # match the mutated moved trade and we'd add it a second time below
        # (yielding a duplicated entry on disk under the destination).
        src_remaining = [t for t in src_trades if t is not moved]
        dst_existing = self._account_trades(destination_account, all_trades)

        # Now retag and build the destination slice.
        moved.account = destination_account
        dst_with_moved = dst_existing + [moved]

        # Source first (drops the moved trade), then destination (adds it).
        # Both writes go through `_run_in_background` so the UI doesn't
        # freeze during the two HTTP roundtrips. We chain them: the
        # destination write only runs after the source write completes,
        # preserving the "drop before add" order that prevents duplicates.
        src_name = account.name

        def _on_src_done(_result):
            self._run_in_background(
                self._store.save_account_trades,
                args=(destination_account, dst_with_moved),
                on_done=lambda _r: self._app.refresh_all_accounts(),
                on_error=lambda msg: QMessageBox.warning(
                    self, "Move Failed (destination)", msg),
                label=f"save_account_trades({destination_account})",
            )

        self._run_in_background(
            self._store.save_account_trades,
            args=(src_name, src_remaining),
            on_done=_on_src_done,
            on_error=lambda msg: QMessageBox.warning(
                self, "Move Failed (source)", msg),
            label=f"save_account_trades({src_name})",
        )

    def _on_set_goal_target(self, value: float) -> None:
        """Update goal target(s) for the current account.

        If the account is part of a shared goal group, ALL accounts in
        the group get the same target (the group has one shared goal).
        The write is backgrounded so the slider in the QML Goal
        Dashboard stays responsive on slow networks.
        """
        account = self._app.currentAccount
        if account is None:
            return
        try:
            shared, _ = self._store.get_goal_group()
            shared_set = set(shared)
        except Exception:
            shared_set = set()

        if account.name in shared_set:
            names = list(shared_set)
        else:
            names = [account.name]

        def _do_writes():
            # Run multiple set_goal_target calls inline in the background
            # thread. Keeps the order deterministic and avoids spawning
            # N threads for what's typically a 2-3-account group.
            for name in names:
                self._store.set_goal_target(name, float(value))

        self._run_in_background(
            _do_writes,
            on_done=lambda _r: self._app.refresh_all_accounts(),
            on_error=lambda msg: QMessageBox.warning(self, "Save Failed", msg),
            label=f"set_goal_target({','.join(names)})",
        )

    # ------------------------------------------------------------------
    # Auto-snapshot (defensive, disk-based)
    # ------------------------------------------------------------------

    def _write_launch_snapshot(self) -> None:
        """Write a defensive backup of current store contents to the
        auto_backups folder, so a sudden bug or accidental wipe can be
        rolled back from a recent launch state.

        Best-effort — failures are swallowed (see io_utils.write_auto_snapshot).
        """
        from .io_utils import write_auto_snapshot
        write_auto_snapshot(self._store, kind="launch")

    # ------------------------------------------------------------------
    # View-menu toggles
    # ------------------------------------------------------------------

    def _on_toggle_hide_equity_curve(self, hide: bool) -> None:
        """View menu → "Hide Equity Curve" checkbox.

        `hide=True` means the user wants the curve gone, so the
        AppController's `equityCurveVisible` flag flips to False. We
        persist the inverted state under "view/EQUITY_CURVE_VISIBLE" so
        existing settings semantics ("visible" = source of truth) stay
        consistent in QSettings.
        """
        visible = not bool(hide)
        self._app.set_equity_curve_visible(visible)
        self._qsettings().setValue("view/EQUITY_CURVE_VISIBLE", visible)
        # Re-evaluate the window minimum — hiding the curve reclaims
        # ~222 px (210 minimumHeight + 12 spacing), letting the user
        # shrink the window further.
        self._apply_minimum_window_size()

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
        # Background the set_goal_group write — the dialog has already
        # closed by the time `exec()` returns, so we just need the UI
        # to refresh once the write lands without freezing during it.
        self._run_in_background(
            self._store.set_goal_group,
            args=(
                dlg.selected_accounts(),
                dlg.shared_goal(),
                dlg.individual_goals(),
                dlg.all_preset_values(),
            ),
            on_done=lambda _r: self._app.refresh_all_accounts(),
            on_error=lambda msg: QMessageBox.warning(self, "Save Failed", msg),
            label="set_goal_group",
        )

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
        # Drill-down — read-only review of every trade for this symbol
        # (closed, open, pending) plus a mini equity curve scoped to it.
        menu.addSeparator()
        menu.addAction(f"View Trade History — {instrument}").triggered.connect(
            lambda: self._safe_run(self._open_symbol_history, instrument, account.name))
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

        # ── Move to portfolio submenu ───────────────────────────────────
        # Lists every other portfolio under the same user account; each
        # entry moves this single trade over there. Skipped entirely if
        # the user only has one portfolio.
        try:
            all_account_names = list(self._store.get_account_names())
        except Exception:
            all_account_names = [account.name]
        other_accounts = [a for a in all_account_names if a != account.name]
        if other_accounts:
            move_menu = menu.addMenu("Move to portfolio")
            for dest in other_accounts:
                act = move_menu.addAction(dest)
                # Default-arg `d=dest` snapshots the loop variable; without
                # this every action would close over the LAST `dest` value.
                act.triggered.connect(
                    lambda _checked=False, d=dest:
                    self._safe_run(self._on_move_trade, source_index, d))

        # Drill-down on the symbol — same dialog as the Holdings menu
        # entry. Useful here because closed-out symbols only appear in
        # the trade history (no holdings row to right-click).
        instr = trade.normalized_instrument()
        if instr:
            menu.addSeparator()
            menu.addAction(f"View All Trades for {instr}").triggered.connect(
                lambda: self._safe_run(self._open_symbol_history, instr, account.name))

        menu.addSeparator()
        menu.addAction("Delete Trade").triggered.connect(
            lambda: self._safe_run(self._on_delete_trade, source_index))
        menu.exec(QCursor.pos())

    def _open_symbol_history(self, instrument: str, account_name: str) -> None:
        """Open the per-symbol drill-down dialog. Pulls the account's
        full trade list (unfiltered) so the dialog shows the complete
        history regardless of any active date-range / tag filter on
        the main window."""
        from .symbol_history_dialog import SymbolHistoryDialog
        all_trades = self._account_trades(account_name, self._all_trades())
        # Look up the most recent mark for this symbol (used by the
        # dialog's header to show the live unrealized P/L).
        marks = getattr(self._app, "_marks_by_symbol", {}) or {}
        info = marks.get(instrument.upper(), {})
        mark = info.get("price") if isinstance(info, dict) else None
        dlg = SymbolHistoryDialog(
            instrument=instrument,
            trades=all_trades,
            current_mark=mark,
            parent=self,
        )
        dlg.exec()

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

    # ------------------------------------------------------------------
    # Export / Backup / Restore
    # ------------------------------------------------------------------

    def _default_export_dir(self) -> str:
        """~/Documents on Windows, ~ everywhere else — a sensible default
        for save-as dialogs."""
        from pathlib import Path
        docs = Path.home() / "Documents"
        return str(docs if docs.exists() else Path.home())

    def _on_export_csv(self) -> None:
        """File → Export Trades to CSV — saves every trade across every
        portfolio for the current user."""
        from datetime import datetime
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from .io_utils import export_trades_to_csv

        default_name = f"stock_insights_trades_{datetime.now():%Y%m%d_%H%M%S}.csv"
        default_path = str(Path(self._default_export_dir()) / default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Trades to CSV", default_path,
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            count = export_trades_to_csv(self._all_trades(), Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))
            return
        QMessageBox.information(
            self, "Export Complete",
            f"Wrote <b>{count}</b> trade{'s' if count != 1 else ''} to:<br>"
            f"<code>{path}</code>",
        )

    def _on_backup(self) -> None:
        """File → Backup All Data — full JSON snapshot of trades + accounts
        + watchlist + goal config. Restorable via 'Restore From Backup…'."""
        from datetime import datetime
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from .io_utils import write_backup

        default_name = f"stock_insights_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
        default_path = str(Path(self._default_export_dir()) / default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup All Data", default_path,
            "Backup files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            written = write_backup(self._store, Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Backup Failed", str(exc))
            return
        QMessageBox.information(
            self, "Backup Saved",
            f"Backup written to:<br><code>{written}</code><br><br>"
            "Keep this file somewhere safe — Restore From Backup will "
            "rebuild every trade, watchlist symbol, and goal setting "
            "from its contents.",
        )

    def _on_restore(self) -> None:
        """File → Restore From Backup — picks a JSON file and overwrites
        the current user's data with its contents.

        Two-phase: PARSE + VALIDATE the snapshot end-to-end before
        running `apply_backup`. This means a corrupt or partially-
        truncated backup is caught BEFORE any data is wiped — the
        previous one-shot flow could leave the store half-restored if
        validation hit a bad row mid-way through.
        """
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from .io_utils import (
            apply_backup, read_backup, validate_backup, write_auto_snapshot,
        )

        path, _ = QFileDialog.getOpenFileName(
            self, "Restore From Backup",
            self._default_export_dir(),
            "Backup files (*.json);;All files (*)",
        )
        if not path:
            return

        # ── Phase 1: parse ─────────────────────────────────────────────
        try:
            snapshot = read_backup(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Backup", str(exc))
            return

        # ── Phase 2: structurally validate (still read-only) ──────────
        # Surface every problem at once so the user sees the full picture,
        # not just the first error. Truncate to the first 10 because beyond
        # that the dialog turns into a wall of text and ceases to be useful.
        errors = validate_backup(snapshot)
        if errors:
            shown = "\n".join(f"  • {e}" for e in errors[:10])
            more = (f"\n  ... and {len(errors) - 10} more error(s)"
                    if len(errors) > 10 else "")
            QMessageBox.warning(
                self, "Invalid Backup",
                "Backup failed validation. Nothing was changed.\n\n"
                f"{shown}{more}",
            )
            return

        # ── Phase 3: confirm with summary ─────────────────────────────
        summary_msg = (
            f"This will <b>overwrite</b> your current data with:<br><br>"
            f"  • {len(snapshot.get('accounts', []))} portfolio(s)<br>"
            f"  • {len(snapshot.get('trades', []))} trade(s)<br>"
            f"  • {len(snapshot.get('watchlist', []))} watchlist symbol(s)<br>"
            f"  • Backup exported at: <code>"
            f"{snapshot.get('exported_at', 'unknown')}</code><br><br>"
            f"Continue?"
        )
        if QMessageBox.question(self, "Restore From Backup", summary_msg) \
                != QMessageBox.StandardButton.Yes:
            return

        # ── Phase 4: defensive auto-snapshot of EXISTING data ─────────
        # Best-effort; if it fails (disk full, perms, etc.) we still let
        # the restore proceed. Written to ~/.stock_insights/auto_backups/
        # so the user can recover if the restore turns out wrong.
        write_auto_snapshot(self._store, kind="pre-restore")

        # ── Phase 5: apply (destructive) ──────────────────────────────
        try:
            result = apply_backup(self._store, snapshot)
        except Exception as exc:
            QMessageBox.warning(self, "Restore Failed", str(exc))
            return

        # Rebuild the UI from the new data
        self._app.rebuild_accounts()
        self._load_watchlist()
        self._app.refresh_all_accounts()

        QMessageBox.information(
            self, "Restore Complete",
            f"Restored <b>{result['trades']}</b> trade(s) across "
            f"<b>{result['accounts']}</b> portfolio(s).<br>"
            f"Watchlist: <b>{result['watchlist']}</b> symbol(s).",
        )

    def _open_user_account_dialog(self) -> None:
        UserAccountDialog(self._store, self).exec()
        # Account list may have changed.
        self._app.rebuild_accounts()
        self._app.refresh_all_accounts()

    def _open_manage_passwords(self) -> None:
        """Admin → Manage User Passwords… — opens the reset-password dialog."""
        if not self._store.is_admin:
            QMessageBox.information(self, "Admin Only",
                                    "Only admin accounts can manage user passwords.")
            return
        _remote_ok = (
                isinstance(self._store, RemoteDataStore) or
                (isinstance(self._store, FallbackDataStore) and self._store._is_online)
        )
        if not _remote_ok:
            QMessageBox.information(
                self, "Server Required",
                "Managing other users' passwords requires a server connection. "
                "The app is currently in offline mode — reconnect first.",
            )
            return
        ManageUserPasswordsDialog(self._store, self).exec()

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
            w.raise_();
            w.activateWindow();
            return
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
        # Server-side /health probe — fires every 15s, much cheaper than
        # the generic netcheck (which hits Google/Cloudflare) and gives
        # us the actual server version + latency for the status pill's
        # tooltip. Skipped entirely when not on a RemoteDataStore.
        self.timer_health = QTimer(self)
        self.timer_health.setInterval(15_000)
        self.timer_health.timeout.connect(self._kick_health_probe)

        self.timer_l1.start() if self.L1_ENABLED else self.timer_l1.stop()
        self.timer_net.start()
        if self._remote_store_for_health() is not None:
            self.timer_health.start()
        # Defer first tick — avoids spawning a QThread before the QML scene
        # has finished mounting (Windows access-violation guard).
        QTimer.singleShot(250, self._kick_netcheck)
        QTimer.singleShot(500, self._level1_tick)
        QTimer.singleShot(800, self._kick_health_probe)

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

    # ── Server health probe ──────────────────────────────────────────
    # Polls /health every 15s on a Remote/Fallback store and stuffs the
    # result into the status pill's tooltip. Adds zero label width —
    # the pill stays "● Online" / "● Offline" — but hovering reveals
    # "Server v1.0.0 · 12 ms · db ok · up 2h 14m" so you can see the
    # actual server state without leaving the app.

    def _remote_store_for_health(self) -> Optional[RemoteDataStore]:
        """Return the underlying RemoteDataStore (if any) for /health calls.

        LocalDataStore-only setups have no server, so health probing is
        a no-op. FallbackDataStore wraps a RemoteDataStore that's still
        addressable even when the fallback is "offline" — the probe
        will fail with a fast timeout, which is also useful info.
        """
        if isinstance(self._store, RemoteDataStore):
            return self._store
        if isinstance(self._store, FallbackDataStore):
            return self._store._remote
        return None

    def _kick_health_probe(self) -> None:
        if self._closing:
            return
        remote = self._remote_store_for_health()
        if remote is None:
            return
        # Use the existing _run_in_background plumbing — same lifecycle
        # rules, no need to spawn a hand-rolled QThread here.
        self._run_in_background(
            remote.ping_health,
            on_done=self._on_health_result,
            on_error=lambda msg: self._on_health_result({"ok": False, "error": msg}),
            label="ping_health",
        )

    def _on_health_result(self, info: dict) -> None:
        if self._closing or not info:
            return
        # Format uptime as "Xh Ym" / "Xm Ys" / "Xs" — readable at a glance.
        secs = int(info.get("uptime_seconds", 0) or 0)
        if secs >= 3600:
            uptime = f"{secs // 3600}h {(secs % 3600) // 60}m"
        elif secs >= 60:
            uptime = f"{secs // 60}m {secs % 60}s"
        else:
            uptime = f"{secs}s"

        if not info.get("ok"):
            # Tooltip surfaces the actual failure (timeout, HTTP 5xx,
            # ConnectionError, etc.) — useful when debugging "why is
            # the pill amber?".
            err = info.get("error") or "no response"
            self.lbl_status.setToolTip(
                f"Server unreachable\nLast probe error: {err}"
            )
            return

        # Success path — build a multi-line tooltip with every signal
        # we have. Newlines + Qt's default rich-tooltip rendering give
        # a tidy hover popup.
        version = info.get("server_version", "?")
        latency = info.get("latency_ms", "?")
        db_state = "ok" if info.get("db_ok") else "down"
        self.lbl_status.setToolTip(
            f"Server v{version}\n"
            f"Latency: {latency} ms\n"
            f"Database: {db_state}\n"
            f"Uptime: {uptime}"
        )

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
