"""main_window.py — QML-hosted main window.

The central widget is a QQuickWidget rendering `qml/Main.qml`. All data
exposed to QML lives behind an AppController defined in qml_bridge.py.
Modal dialogs (login, settings, trade edit, etc.) remain QWidget-based —
forms are exactly what QWidget is good at.

What lives here
───────────────
• Menu bar and the status corner (connection state, "Updating prices").
• ThemeManager wiring + initial theme application.
• Timers + single-flight workers: marks refresh, connectivity check,
  server /health probe, reconnect (background.py does the thread plumbing).
• Watchlist persistence and add/remove/rename slots called by QML.
• Trade CRUD callbacks called by QML — they open the dialogs in
  stock_insights/dialogs and persist via the DataStore in the background,
  one trade per save (DataStore.save_trade / delete_trade, keyed by
  Trade.uid), never the whole account.
• Admin entry points (view another user's portfolio, reset passwords).

File menu export / backup / restore live in file_actions.py.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Importing QtCharts here is required even though we don't reference any
# of its Python symbols — the import is what registers the `QtCharts`
# QML module (ChartView, LineSeries, DateTimeAxis, ValueAxis used by
# EquityCurveCard.qml). Without it the QML engine silently fails to
# instantiate ChartView and the curve renders as a blank area.
from PySide6 import QtCharts  # noqa: F401  (side-effect import)
from PySide6.QtCore import QSettings, QTimer, QUrl, Qt, Signal
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
    QSizePolicy,
    QWidget,
)

from . import file_actions
from .admin_dialogs import (
    ManageUserPasswordsDialog,
    SelectUserDialog,
    UserAccountDialog,
    UserPortfolioViewer,
)
from .api_client import DataStore, FallbackDataStore, RemoteDataStore
from .background import BackgroundCalls, SingleFlight
from .dialogs import (
    DoubleDownDialog,
    FulfillOrderDialog,
    GoalDashboardOptionsDialog,
    MarkDownDialog,
    TradeEditDialog,
)
from .logging_utils import get_logger, serial_debug, setup_logging
from .portfolio import Holding, Trade
from .qml_bridge import AppController
from .theme import FONT_SIZES, ThemeManager
from .widgets import SpinnerLabel, confirm, set_text_role, theme_color
from .workers import MarksWorker, NetCheckWorker, ReconnectWorker

_ORG = "StockInsights"
_APP = "StocksGUI"
_QML_DIR = Path(__file__).resolve().parent / "qml"

HEALTH_INTERVAL_MS = 15_000
RECONNECT_INTERVAL_MS = 30_000
_SYMBOL_HINT = "Symbols use letters, numbers, dots and dashes, like NVDA or BRK.B."

# Connection states shown in the status corner: label, text role, tooltip.
# Gain/loss colours carry the meaning; the words say the same thing so the
# state never relies on colour alone.
_SERVER_DOWN_TIP = ("Can't reach the sync server. Changes are saved here and "
                    "will sync when it's back.")
_CONNECTION_STATES: Dict[str, Tuple[str, str, str]] = {
    "connecting": ("Connecting…", "muted", ""),
    "online": ("Online", "good", ""),
    "syncing": ("Online, syncing changes", "good", ""),
    "synced": ("Online, synced {n} {changes}", "good", ""),
    "server_down": ("Sync server unreachable", "bad", _SERVER_DOWN_TIP),
    "queued": ("Sync paused, {n} {changes} waiting", "bad", _SERVER_DOWN_TIP),
    "offline": ("Offline", "bad", "No internet connection. Prices won't update until you're back online."),
    "offline_queued": ("Offline, {n} {changes} waiting", "bad", _SERVER_DOWN_TIP),
    "local": ("Working offline", "muted",
              "Signed in offline. Your data is saved on this computer only."),
}


def _valid_symbol(sym: str) -> bool:
    return bool(sym) and all(ch.isalnum() or ch in ".-" for ch in sym)


def _open_lots(trades: List[Trade], instrument: str, is_short: Optional[bool] = None) -> List[Trade]:
    """Filled, still-open trades for `instrument` (optionally one side only)."""
    return [t for t in trades
            if not t.is_closed and not t.is_pending
            and (is_short is None or t.is_short == is_short)
            and t.normalized_instrument() == instrument]


def _combined_lot(instrument: str, lots: List[Trade]) -> Tuple[int, float]:
    """(total shares, average cost) across `lots`; (0, 0.0) when empty."""
    qty = sum(int(t.share_count) for t in lots)
    cost = sum(float(t.buy_price) * int(t.share_count) for t in lots)
    return qty, (cost / qty) if qty > 0 else 0.0


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

    # FallbackDataStore reports offline/online from whichever thread did the
    # store call (usually a background worker). Re-emitting through these
    # signals queues the status update onto the GUI thread.
    _offlineReported = Signal(int)
    _syncedReported = Signal(int)

    def __init__(self, store: DataStore):
        super().__init__()
        setup_logging()
        serial_debug("MainWindow init start")

        self._store = store
        self._closing = False
        self._busy_ops = 0
        self._online = True
        self._marks_error: Optional[str] = None
        self._viewer_windows: Dict[int, UserPortfolioViewer] = {}
        self._reconnect_timer_obj: Optional[QTimer] = None

        # Thread plumbing (see background.py).
        self._bg = BackgroundCalls(self)
        self._marks_flight = SingleFlight(self, "marks")
        self._netcheck_flight = SingleFlight(self, "netcheck")
        self._reconnect_flight = SingleFlight(self, "reconnect")

        self._offlineReported.connect(self._set_offline_status)
        self._syncedReported.connect(self._set_synced_status)
        if isinstance(store, FallbackDataStore):
            store._on_offline_cb = self._offlineReported.emit
            store._on_online_cb = self._syncedReported.emit

        self.setWindowTitle(f"Stock Insights — {store.username}")
        self.resize(1280, 820)

        # ── ThemeManager (created early so AppController can reference it) ──
        self.theme = ThemeManager(self)
        s = self._qsettings()
        self.theme.override_mode = s.value("ui/THEME_OVERRIDE", "System", type=str)
        self.theme.match_system_accent = s.value("ui/MATCH_SYSTEM_ACCENT", True, type=bool)
        self.theme.theme_name = s.value("ui/THEME_NAME", "Default", type=str)
        self.theme.font_size_label = s.value("ui/FONT_SIZE", "Normal", type=str)
        self.L1_INTERVAL = int(s.value("intervals/L1_INTERVAL", self.L1_INTERVAL))
        self.NET_INTERVAL = int(s.value("intervals/NET_INTERVAL", self.NET_INTERVAL))
        self.L1_ENABLED = bool(s.value("intervals/L1_ENABLED", True, type=bool))

        # ── AppController bridges store + theme into QML ──
        self._app = AppController(self._store, self.theme, self)
        # Apply view-menu preferences before QML mounts so the affected
        # cards don't flash visible and then collapse.
        self._app.set_equity_curve_visible(
            s.value("view/EQUITY_CURVE_VISIBLE", True, type=bool)
        )
        # All QML-triggered handlers that open modal QDialogs / QMenus run
        # through _safe_run so the QML callback unwinds before the dialog
        # opens (avoids nested-event-loop crashes on Windows + QQuickWidget).
        self._app.set_callbacks({
            "add_ticker": lambda: self._safe_run(self._on_add_ticker),
            "remove_ticker": lambda r: self._safe_run(self._on_remove_ticker, r),
            "rename_ticker": lambda r, sym: self._safe_run(self._on_rename_ticker, r, sym),
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
        # the empty-state placeholder never flashes during the first render.
        self._app.refresh_all_accounts()

        # Launch snapshot to ~/.stock_insights/auto_backups/, deferred so it
        # doesn't delay the first paint. Best-effort (io_utils swallows errors).
        QTimer.singleShot(0, self._write_launch_snapshot)

        self._build_menus()
        self._build_status_corner()
        self._build_qml_host()

        # Apply theme + start watching for OS theme changes.
        self.theme.apply()
        self.theme.themeApplied.connect(self._app.theme.refresh)
        # Font size changes grow the QML widgets (app.theme.fontScale); bump
        # the window minimum too so nothing gets cropped.
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
    # The QML page scrolls vertically, so the minimum height only has to fit
    # the menu bar, tab bar and the top of the first card; 640 also fits a
    # 1440x900 screen at "Normal" text size.
    _BASE_MIN_HEIGHT = 640
    # Height reclaimed when the equity curve is hidden. Zero now that the page
    # scrolls (kept so the View toggle can still re-evaluate the minimum).
    _EQUITY_CURVE_HEIGHT_COST = 0

    def _current_font_scale(self) -> float:
        return float(FONT_SIZES.get(self.theme.font_size_label, 11)) / 11.0

    def _apply_minimum_window_size(self) -> None:
        scale = self._current_font_scale()
        w = int(self._BASE_MIN_WIDTH * scale)
        base_h = self._BASE_MIN_HEIGHT
        if hasattr(self, "_app") and not self._app.equityCurveVisible:
            base_h -= self._EQUITY_CURVE_HEIGHT_COST
        h = int(base_h * scale)
        self.setMinimumSize(w, h)
        # Grow the window if it is now below the minimum (e.g. X-Large font).
        cur = self.size()
        if cur.width() < w or cur.height() < h:
            self.resize(max(cur.width(), w), max(cur.height(), h))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _qsettings(self) -> QSettings:
        return QSettings(self.ORG, self.APP)

    def _all_trades(self) -> List[Trade]:
        # Served from the store's cache in the common case; after a write the
        # cache is cold and this is a network GET on the GUI thread.
        try:
            return list(self._store.get_all_trades())
        except Exception:
            get_logger("ui").exception("get_all_trades failed")
            return []

    def _account_trades(self, account_name: str, all_trades: List[Trade]) -> List[Trade]:
        return [t for t in all_trades if (t.account or "").strip() == account_name]

    def _current_account_trades(self) -> Tuple[Optional[object], List[Trade]]:
        """(current account controller, its trades) or (None, [])."""
        account = self._app.currentAccount
        if account is None:
            return None, []
        return account, self._account_trades(account.name, self._all_trades())

    def _warn_save_failed(self, message: str) -> None:
        QMessageBox.warning(
            self, "Couldn't save",
            f"Your change wasn't saved.\n\n{message}\n\n"
            "Try again. If it keeps failing, use File > Back up data to keep a copy.")

    def _save_trades(self, account_name: str, trades: List[Trade], failure_note: str = "") -> None:
        """Persist the given trades into `account_name`, one request per
        trade, on a background thread; then refresh the QML models on the
        GUI thread. A trade currently in another account is moved.

        Pass copies (dataclasses.replace), not objects read from the store:
        those are shared with the store's cache, and changing them before
        the save is confirmed would show an edit that may not have happened.
        """
        trades = list(trades)
        if not trades:
            return

        def _write() -> None:
            for trade in trades:
                self._store.save_trade(account_name, trade)

        self._run_in_background(
            _write,
            on_done=lambda _result: self._app.refresh_all_accounts(),
            on_error=lambda msg: self._on_trade_write_failed(f"{failure_note}{msg}"),
            label=f"save_trade({account_name}, {len(trades)})",
        )

    def _delete_trade(self, account_name: str, uid: str) -> None:
        """Delete one trade by uid in the background, then refresh."""
        self._run_in_background(
            self._store.delete_trade,
            args=(account_name, uid),
            on_done=lambda _result: self._app.refresh_all_accounts(),
            on_error=self._on_trade_write_failed,
            label=f"delete_trade({account_name})",
        )

    def _on_trade_write_failed(self, message: str) -> None:
        # Part of a multi-trade save may have gone through; show what the
        # store holds now rather than what the user last saw.
        self._app.refresh_all_accounts()
        self._warn_save_failed(message)

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
                    QMessageBox.warning(self, "Something went wrong",
                                        f"{exc}\n\nTry again. Details are in the app log.")
                except RuntimeError:
                    pass

        QTimer.singleShot(0, _wrap)

    def _run_in_background(self, fn, args=(), kwargs=None,
                           on_done=None, on_error=None,
                           label: str = "store-call") -> None:
        """Run `fn(*args, **kwargs)` on a background QThread, then call
        `on_done(result)` or `on_error(message)` on the GUI thread.

        For fire-and-update flows (store writes over the network, /health)
        so the UI stays responsive on slow links. Not for data the next
        paint needs. See background.BackgroundCalls.
        """
        self._bg.run(fn, args=args, kwargs=kwargs, on_done=on_done, on_error=on_error, label=label)

    def _trade_default_quantity(self) -> int:
        try:
            return max(1, int(self._qsettings().value("trade_defaults/default_quantity", 1) or 1))
        except (TypeError, ValueError):
            return 1

    def _trade_quantity_increment(self) -> int:
        try:
            return max(1, int(self._qsettings().value("trade_defaults/quantity_increment", 1) or 1))
        except (TypeError, ValueError):
            return 1

    def _trade_dialog(self, trade: Optional[Trade] = None, **mode) -> TradeEditDialog:
        """TradeEditDialog pre-filled with the watchlist + trade defaults."""
        return TradeEditDialog(
            trade,
            watchlist_symbols=self._app.watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
            **mode,
        )

    def _current_mark(self, instrument: str) -> Optional[float]:
        info = (getattr(self._app, "_marks_by_symbol", {}) or {}).get(instrument.upper(), {})
        price = info.get("price") if isinstance(info, dict) else None
        return float(price) if price is not None else None

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        act_settings = file_menu.addAction("Settings…")
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self._open_settings_dialog)
        file_menu.addAction("Account and portfolios…").triggered.connect(self._open_user_account_dialog)
        file_menu.addSeparator()

        act_export = file_menu.addAction("Export CSV…")
        act_export.setShortcut("Ctrl+E")
        act_export.triggered.connect(lambda: self._safe_run(self._on_export_csv))
        file_menu.addAction("Back up data…").triggered.connect(lambda: self._safe_run(self._on_backup))
        file_menu.addAction("Restore from backup…").triggered.connect(lambda: self._safe_run(self._on_restore))

        file_menu.addSeparator()
        file_menu.addAction("Check for updates…").triggered.connect(self._check_for_updates)
        file_menu.addSeparator()
        act_quit = file_menu.addAction("Quit")
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)

        view_menu = self.menuBar().addMenu("&View")
        act_refresh = view_menu.addAction("Refresh prices")
        act_refresh.setShortcut(QKeySequence("F5"))
        act_refresh.triggered.connect(self._level1_tick)
        view_menu.addSeparator()
        # Checkable: ticked = curve hidden. Persisted inverted as
        # "view/EQUITY_CURVE_VISIBLE" (see _on_toggle_hide_equity_curve).
        self.act_hide_equity_curve = QAction("Hide equity curve", self)
        self.act_hide_equity_curve.setCheckable(True)
        self.act_hide_equity_curve.setChecked(not self._app.equityCurveVisible)
        self.act_hide_equity_curve.toggled.connect(self._on_toggle_hide_equity_curve)
        view_menu.addAction(self.act_hide_equity_curve)
        view_menu.addSeparator()
        view_menu.addAction("Goal options…").triggered.connect(self._on_open_goal_options)

        admin_menu = self.menuBar().addMenu("&Admin")
        self.act_view_user_portfolio = admin_menu.addAction("View a user's portfolio…")
        self.act_view_user_portfolio.triggered.connect(lambda: self._safe_run(self._open_view_user_portfolio))
        self.act_manage_passwords = admin_menu.addAction("Reset a user's password…")
        self.act_manage_passwords.triggered.connect(lambda: self._safe_run(self._open_manage_passwords))
        for act in (self.act_view_user_portfolio, self.act_manage_passwords):
            act.setVisible(self._store.is_admin)
        admin_menu.menuAction().setVisible(self._store.is_admin)

    def _build_status_corner(self) -> None:
        self.spinner = SpinnerLabel()
        self.spinner.setFixedWidth(14)
        set_text_role(self.spinner, "muted")
        self.lbl_updating = QLabel("")
        self.lbl_updating.setObjectName("menuUpdatingLabel")
        set_text_role(self.lbl_updating, "muted")
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("menuOnlineLabel")
        for lbl in (self.lbl_updating, self.lbl_status):
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        status_corner = QWidget(self)
        status_corner.setObjectName("menuStatusCorner")
        row = QHBoxLayout(status_corner)
        row.setContentsMargins(8, 2, 12, 3)
        row.setSpacing(8)
        row.addWidget(self.spinner)
        row.addWidget(self.lbl_updating)
        row.addSpacing(4)
        row.addWidget(self.lbl_status)
        self.menuBar().setCornerWidget(status_corner, Qt.Corner.TopRightCorner)
        self.statusBar().hide()

        if isinstance(self._store, (RemoteDataStore, FallbackDataStore)):
            self._set_connection_state("connecting")
        else:
            self._set_connection_state("local")

    def _build_qml_host(self) -> None:
        self.qml_widget = QQuickWidget()
        self.qml_widget.engine().rootContext().setContextProperty("app", self._app)
        self.qml_widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        # See-through so the QMainWindow palette shows at the borders during
        # a resize (no white flicker).
        self.qml_widget.setClearColor(QColor(0, 0, 0, 0))
        self.qml_widget.setSource(QUrl.fromLocalFile(str(_QML_DIR / "Main.qml")))
        if self.qml_widget.status() == QQuickWidget.Status.Error:
            errors = "\n".join(str(e) for e in self.qml_widget.errors())
            get_logger("qml").error("QML failed to load:\n%s", errors)
        self.setCentralWidget(self.qml_widget)

    # ------------------------------------------------------------------
    # Status corner
    # ------------------------------------------------------------------

    def _set_connection_state(self, state: str, count: int = 0) -> None:
        """Show one of `_CONNECTION_STATES` in the status corner.

        A repeat of the current state is a no-op, so the periodic netcheck
        does not wipe the /health details in the tooltip.
        """
        if (state, count) == getattr(self, "_connection_key", None):
            return
        self._connection_key = (state, count)
        self._connection_state = state
        text, role, tip = _CONNECTION_STATES.get(state, _CONNECTION_STATES["online"])
        self.lbl_status.setText("● " + text.format(n=count, changes="change" if count == 1 else "changes"))
        self.lbl_status.setToolTip(tip)
        set_text_role(self.lbl_status, role)
        self._mirror_status_to_qml()

    def _mirror_status_to_qml(self) -> None:
        """Copy the status text + colour to AppController.statusText/statusColor."""
        role = self.lbl_status.property("role") or "muted"
        token = role if role in ("good", "bad") else "text_muted"
        self._app.set_status(self.lbl_status.text(), theme_color(token, self).name())

    def update_ui(self) -> None:
        """Called by ThemeManager.apply() after a theme change. Labels
        re-colour themselves; only the QML mirror needs a nudge."""
        if hasattr(self, "lbl_status"):
            self._mirror_status_to_qml()

    # ------------------------------------------------------------------
    # Watchlist persistence + slots wired from QML
    # ------------------------------------------------------------------

    def _load_watchlist(self) -> None:
        try:
            symbols = self._store.get_watchlist()
        except Exception:
            get_logger("ui").exception("get_watchlist failed")
            symbols = []
        if not symbols:
            raw = self._qsettings().value("watchlist/items", [])
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = []
            if isinstance(raw, list) and raw:
                symbols = [str(t).upper() for t in raw if str(t).strip()]
            if not symbols:
                symbols = list(self.DEFAULT_WATCHLIST)
        self._app.set_watchlist([str(s).upper() for s in symbols])

    def _save_watchlist(self) -> None:
        """Persist the watchlist: remote in the background (best-effort; a
        FallbackDataStore queues failures), local QSettings synchronously so
        a crash right after the change cannot lose it."""
        symbols = self._app.watchlist_symbols()
        self._run_in_background(
            self._store.save_watchlist,
            args=(list(symbols),),
            on_error=lambda msg: get_logger("ui").warning("save_watchlist failed: %s", msg),
            label="save_watchlist",
        )
        s = self._qsettings()
        s.setValue("watchlist/items", symbols)
        s.sync()

    def _on_add_ticker(self) -> None:
        text, ok = QInputDialog.getText(self, "Add to watchlist", "Symbol")
        if not ok or not text.strip():
            return
        sym = text.strip().upper()
        if not _valid_symbol(sym):
            QMessageBox.warning(self, "Add to watchlist", f"“{sym}” isn't a valid symbol.\n\n{_SYMBOL_HINT}")
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
        if not confirm(self, "Remove from watchlist", f"Remove {sym} from your watchlist?", "Remove"):
            return
        del symbols[row]
        self._app.set_watchlist(symbols)
        self._save_watchlist()

    def _on_rename_ticker(self, row: int, new_symbol: str) -> None:
        symbols = self._app.watchlist_symbols()
        if not (0 <= row < len(symbols)):
            return
        sym = (new_symbol or "").strip().upper()
        if not _valid_symbol(sym):
            QMessageBox.warning(self, "Rename symbol", f"“{sym}” isn't a valid symbol.\n\n{_SYMBOL_HINT}")
            return
        if sym in symbols:
            QMessageBox.information(self, "Rename symbol", f"{sym} is already on your watchlist.")
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
        dlg = self._trade_dialog()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        trade = dlg.to_trade()  # a new Trade, so it carries a new uid
        trade.account = account.name
        self._save_trades(account.name, [trade])

    def _on_edit_trade(self, source_index: int) -> None:
        account, account_trades = self._current_account_trades()
        if account is None or not (0 <= source_index < len(account_trades)):
            return
        trade = account_trades[source_index]
        dlg = self._trade_dialog(trade)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.to_trade()
        # The dialog builds a new Trade; it is still the same trade.
        updated.uid = trade.uid
        updated.account = (trade.account or account.name).strip() or account.name
        self._save_trades(updated.account, [updated])

    def _on_delete_trade(self, source_index: int) -> None:
        account, account_trades = self._current_account_trades()
        if account is None or not (0 <= source_index < len(account_trades)):
            return
        trade = account_trades[source_index]
        if not confirm(self, "Delete trade",
                       f"Delete the {trade.normalized_instrument()} trade for "
                       f"{trade.share_count:,d} shares?",
                       "Delete trade", destructive=True, detail="This can't be undone."):
            return
        self._delete_trade(account.name, trade.uid)

    def _on_move_trade(self, source_index: int, destination_account: str) -> None:
        """Move one trade from the current portfolio to another of this user's
        portfolios (trade-history right-click menu).

        A move is one save of the trade under the destination account: the
        store (and the server) find it by uid and re-home it.
        """
        account = self._app.currentAccount
        if account is None or destination_account == account.name:
            return
        src_trades = self._account_trades(account.name, self._all_trades())
        if not (0 <= source_index < len(src_trades)):
            return
        moved = src_trades[source_index]

        if not confirm(self, "Move trade",
                       f"Move the {moved.normalized_instrument()} trade ({moved.share_count:,d} shares) "
                       f"from {account.name} to {destination_account}?",
                       "Move trade"):
            return

        self._save_trades(
            destination_account, [replace(moved, account=destination_account)],
            failure_note=f"The trade couldn't be moved to {destination_account}: ")

    def _on_set_goal_target(self, value: float) -> None:
        """Update goal target(s) for the current account. Accounts in the
        shared goal group all get the same target. Backgrounded so the QML
        slider stays responsive on slow networks."""
        account = self._app.currentAccount
        if account is None:
            return
        try:
            shared, _ = self._store.get_goal_group()
            shared_set = set(shared)
        except Exception:
            get_logger("ui").exception("get_goal_group failed")
            shared_set = set()
        names = list(shared_set) if account.name in shared_set else [account.name]

        def _do_writes():
            # One thread, sequential writes: deterministic order and no
            # thread per account for what is typically 2-3 accounts.
            for name in names:
                self._store.set_goal_target(name, float(value))

        self._run_in_background(
            _do_writes,
            on_done=lambda _r: self._app.refresh_all_accounts(),
            on_error=self._warn_save_failed,
            label=f"set_goal_target({','.join(names)})",
        )

    # ------------------------------------------------------------------
    # Auto-snapshot (defensive, disk-based)
    # ------------------------------------------------------------------

    def _write_launch_snapshot(self) -> None:
        """Defensive backup of the store at launch so an accidental wipe can
        be rolled back. Best-effort (see io_utils.write_auto_snapshot)."""
        from .io_utils import write_auto_snapshot
        write_auto_snapshot(self._store, kind="launch")

    # ------------------------------------------------------------------
    # View-menu toggles
    # ------------------------------------------------------------------

    def _on_toggle_hide_equity_curve(self, hide: bool) -> None:
        """View > Hide equity curve. Persists the *visible* flag
        ("view/EQUITY_CURVE_VISIBLE") and re-evaluates the window minimum."""
        visible = not bool(hide)
        self._app.set_equity_curve_visible(visible)
        self._qsettings().setValue("view/EQUITY_CURVE_VISIBLE", visible)
        self._apply_minimum_window_size()

    # ------------------------------------------------------------------
    # Goal options dialog
    # ------------------------------------------------------------------

    def _on_open_goal_options(self) -> None:
        try:
            accounts = self._store.get_account_names()
            shared_names, _shared_goal = self._store.get_goal_group()
        except Exception as exc:
            QMessageBox.warning(self, "Goal options",
                                f"Couldn't load your goals.\n\n{exc}\n\nCheck your connection and try again.")
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
        self._run_in_background(
            self._store.set_goal_group,
            args=(dlg.selected_accounts(), dlg.shared_goal(), dlg.individual_goals(),
                  dlg.all_preset_values()),
            on_done=lambda _r: self._app.refresh_all_accounts(),
            on_error=self._warn_save_failed,
            label="set_goal_group",
        )

    def _on_open_trade_history_options(self) -> None:
        """QML callback (the View menu no longer lists it: there is nothing
        to configure in the QML trade table)."""
        QMessageBox.information(
            self, "Trade history",
            "Click a column header to sort. Use the filter box and the status "
            "menu above the table to narrow the rows.",
        )

    # ------------------------------------------------------------------
    # Context menus driven by QML right-clicks
    # ------------------------------------------------------------------

    def _on_holdings_menu(self, instrument: str) -> None:
        account, account_trades = self._current_account_trades()
        if account is None or not instrument:
            return
        open_long = _open_lots(account_trades, instrument, is_short=False)
        open_short = _open_lots(account_trades, instrument, is_short=True)
        if not open_long and not open_short:
            return
        is_short = bool(open_short) and not open_long

        menu = QMenu(self)
        # Each action defers via _safe_run so the dialog opens after the
        # QMenu's exec loop has unwound (QML → menu → dialog nesting crashes
        # intermittently on Windows).
        if is_short:
            menu.addAction("Buy to cover…").triggered.connect(
                lambda: self._safe_run(self._close_position, instrument, account.name, account_trades, True))
        else:
            menu.addAction("Close position…").triggered.connect(
                lambda: self._safe_run(self._close_position, instrument, account.name, account_trades, False))
            menu.addAction("Mark down…").triggered.connect(
                lambda: self._safe_run(self._mark_down, instrument, account.name, account_trades))
            menu.addAction("Double down…").triggered.connect(
                lambda: self._safe_run(self._double_down, instrument, account.name, account_trades))
        menu.addSeparator()
        menu.addAction(f"View {instrument} trade history").triggered.connect(
            lambda: self._safe_run(self._open_symbol_history, instrument, account.name))
        menu.exec(QCursor.pos())

    def _close_position(self, instrument: str, account_name: str,
                        account_trades: List[Trade], is_short: bool) -> None:
        matching = _open_lots(account_trades, instrument, is_short=is_short)
        if not matching:
            return
        total_qty, avg_cost = _combined_lot(instrument, matching)
        combined = Trade(
            instrument=instrument, share_count=total_qty, buy_price=avg_cost,
            sell_price=None,
            open_date=min((t.open_date for t in matching if t.open_date), default=date.today()),
            close_date=None, notes=" | ".join(t.notes for t in matching if t.notes),
            is_short=is_short,
        )
        dlg = self._trade_dialog(combined, close_holdings_mode=not is_short, cover_mode=is_short)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        closing = dlg.to_trade()
        if closing.sell_price is None or closing.close_date is None:
            return
        # A position can be several lots; each is its own trade and is saved
        # on its own (all in one background call, in order).
        self._save_trades(account_name, [
            replace(t, sell_price=float(closing.sell_price), close_date=closing.close_date)
            for t in matching
        ])

    def _holding_for(self, instrument: str, account_trades: List[Trade]) -> Optional[Holding]:
        qty, avg = _combined_lot(instrument, _open_lots(account_trades, instrument, is_short=False))
        if qty <= 0:
            return None
        return Holding(instrument=instrument, qty=qty, avg_cost=avg, notes="")

    def _append_trade(self, dlg, account_name: str) -> None:
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        trade = dlg.to_trade()
        trade.account = account_name
        self._save_trades(account_name, [trade])

    def _mark_down(self, instrument: str, account_name: str, account_trades: List[Trade]) -> None:
        holding = self._holding_for(instrument, account_trades)
        if holding is None:
            return
        dlg = MarkDownDialog(
            holding=holding,
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        self._append_trade(dlg, account_name)

    def _double_down(self, instrument: str, account_name: str, account_trades: List[Trade]) -> None:
        holding = self._holding_for(instrument, account_trades)
        if holding is None:
            return
        dlg = DoubleDownDialog(
            holding=holding, current_mark=self._current_mark(instrument),
            quantity_increment=self._trade_quantity_increment(), parent=self,
        )
        self._append_trade(dlg, account_name)

    def _on_trade_menu(self, source_index: int) -> None:
        account, account_trades = self._current_account_trades()
        if account is None or not (0 <= source_index < len(account_trades)):
            return
        trade = account_trades[source_index]
        menu = QMenu(self)
        # Dialog opens are deferred via _safe_run — see _on_holdings_menu.
        if trade.is_pending:
            menu.addAction("Mark order filled…").triggered.connect(
                lambda: self._safe_run(self._fulfill_pending, source_index))
            menu.addSeparator()
        menu.addAction("Edit trade…").triggered.connect(
            lambda: self._safe_run(self._on_edit_trade, source_index))

        # "Move to portfolio" lists this user's other portfolios; hidden when
        # there is only one.
        try:
            all_account_names = list(self._store.get_account_names())
        except Exception:
            all_account_names = [account.name]
        other_accounts = [a for a in all_account_names if a != account.name]
        if other_accounts:
            move_menu = menu.addMenu("Move to portfolio")
            for dest in other_accounts:
                # `d=dest` snapshots the loop variable for the lambda.
                move_menu.addAction(dest).triggered.connect(
                    lambda _checked=False, d=dest: self._safe_run(self._on_move_trade, source_index, d))

        # Closed-out symbols only appear in the trade history, so the
        # drill-down is offered here as well as on holdings.
        instr = trade.normalized_instrument()
        if instr:
            menu.addSeparator()
            menu.addAction(f"View {instr} trade history").triggered.connect(
                lambda: self._safe_run(self._open_symbol_history, instr, account.name))

        menu.addSeparator()
        menu.addAction("Delete trade…").triggered.connect(
            lambda: self._safe_run(self._on_delete_trade, source_index))
        menu.exec(QCursor.pos())

    def _open_symbol_history(self, instrument: str, account_name: str) -> None:
        """Per-symbol drill-down over the account's full (unfiltered) trade
        list, with the latest mark for the unrealized P/L line."""
        from .symbol_history_dialog import SymbolHistoryDialog
        dlg = SymbolHistoryDialog(
            instrument=instrument,
            trades=self._account_trades(account_name, self._all_trades()),
            current_mark=self._current_mark(instrument),
            parent=self,
        )
        dlg.exec()

    def _fulfill_pending(self, source_index: int) -> None:
        account, account_trades = self._current_account_trades()
        if account is None or not (0 <= source_index < len(account_trades)):
            return
        trade = account_trades[source_index]
        if not trade.is_pending:
            QMessageBox.information(self, "Mark order filled", "This trade is already filled.")
            return
        dlg = FulfillOrderDialog(trade, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_trades(account.name, [replace(
            trade, is_pending=False,
            open_date=dlg.get_fill_date(), buy_price=dlg.get_fill_price(),
        )])

    # ------------------------------------------------------------------
    # Settings / updates / user account dialogs
    # ------------------------------------------------------------------

    def _open_settings_dialog(self) -> None:
        from .settings_dialog import SettingsDialog
        s = self._qsettings()
        cv = {
            "L1_INTERVAL": self.L1_INTERVAL, "NET_INTERVAL": self.NET_INTERVAL,
            "L1_ENABLED": self.L1_ENABLED,
            "THEME_OVERRIDE": self.theme.override_mode,
            "MATCH_SYSTEM_ACCENT": self.theme.match_system_accent,
            "THEME_NAME": self.theme.theme_name,
            "FONT_SIZE": self.theme.font_size_label,
            "TRADE_DEFAULT_QUANTITY": self._trade_default_quantity(),
            "TRADE_QUANTITY_INCREMENT": self._trade_quantity_increment(),
        }
        dlg = SettingsDialog(self, s, cv)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        vals = dlg.get_values()
        self.L1_INTERVAL = int(vals["L1_INTERVAL"])
        self.NET_INTERVAL = int(vals["NET_INTERVAL"])
        self.L1_ENABLED = bool(vals["L1_ENABLED"])
        # Set all theme fields, then apply once (each set_* re-applies the
        # whole stylesheet, which is slow and flickers).
        self.theme.override_mode = vals["THEME_OVERRIDE"] if vals["THEME_OVERRIDE"] in (
            "System", "Light", "Dark") else "System"
        self.theme.match_system_accent = bool(vals["MATCH_SYSTEM_ACCENT"])
        self.theme.theme_name = vals.get("THEME_NAME", "Default")
        self.theme.font_size_label = vals.get("FONT_SIZE", "Normal") if vals.get(
            "FONT_SIZE") in FONT_SIZES else "Normal"
        self.theme.set_theme(self.theme.theme_name)  # validates the name + applies
        s.setValue("trade_defaults/default_quantity", int(vals["TRADE_DEFAULT_QUANTITY"]))
        s.setValue("trade_defaults/quantity_increment", int(vals["TRADE_QUANTITY_INCREMENT"]))
        self._save_settings(remote=False)
        self.timer_l1.setInterval(self.L1_INTERVAL)
        self.timer_net.setInterval(self.NET_INTERVAL)
        if self.L1_ENABLED:
            self.timer_l1.start()
        else:
            self.timer_l1.stop()

    def _check_for_updates(self) -> None:
        from .update_checker import check_for_updates
        check_for_updates(parent=self, silent_if_current=False)

    # ------------------------------------------------------------------
    # Export / Backup / Restore (file_actions.py does the work)
    # ------------------------------------------------------------------

    def _default_export_dir(self) -> str:
        return file_actions.default_export_dir()

    def _on_export_csv(self) -> None:
        file_actions.export_csv(self, self._all_trades())

    def _on_backup(self) -> None:
        file_actions.back_up(self, self._store)

    def _on_restore(self) -> None:
        """Validate + confirm on the GUI thread, then write the pre-restore
        auto-snapshot and apply the backup in the background (both go
        through the store, which may mean many network calls)."""
        snapshot = file_actions.choose_restore(self)
        if snapshot is None:
            return
        from .io_utils import apply_backup, write_auto_snapshot
        store = self._store

        def _restore():
            write_auto_snapshot(store, kind="pre-restore")  # best-effort
            return apply_backup(store, snapshot)

        def _done(result):
            self._app.rebuild_accounts()
            self._load_watchlist()
            self._app.refresh_all_accounts()
            self._busy_leave()
            file_actions.show_restore_result(self, result)

        def _failed(msg):
            self._busy_leave()
            file_actions.show_restore_failed(self, msg)

        self._busy_enter("Restoring backup…")
        self._run_in_background(_restore, on_done=_done, on_error=_failed, label="apply_backup")

    # ------------------------------------------------------------------
    # Account + admin dialogs
    # ------------------------------------------------------------------

    def _open_user_account_dialog(self) -> None:
        UserAccountDialog(self._store, self).exec()
        # Portfolio list may have changed.
        self._app.rebuild_accounts()
        self._app.refresh_all_accounts()

    def _server_available(self, title: str, action: str) -> bool:
        """Admin actions need the server; explain and return False if not."""
        if not self._store.is_admin:
            QMessageBox.information(self, title, f"Only admin accounts can {action}.")
            return False
        remote_ok = (isinstance(self._store, RemoteDataStore)
                     or (isinstance(self._store, FallbackDataStore) and self._store._is_online))
        if not remote_ok:
            QMessageBox.information(
                self, title,
                f"You need a connection to the sync server to {action}. "
                "The app is offline right now; it reconnects automatically every 30 seconds.")
            return False
        return True

    def _with_user_list(self, title: str, then) -> None:
        """Fetch the user list in the background, then call `then(users)`."""
        def _failed(msg: str) -> None:
            self._busy_leave()
            QMessageBox.warning(self, title, f"Couldn't load the user list.\n\n{msg}\n\nTry again in a moment.")

        def _done(users) -> None:
            self._busy_leave()
            then(list(users or []))

        self._busy_enter("Loading users…")
        self._run_in_background(self._store.list_users, on_done=_done, on_error=_failed, label="list_users")

    def _open_manage_passwords(self) -> None:
        """Admin > Reset a user's password."""
        title = "Reset a user's password"
        if not self._server_available(title, "reset other users' passwords"):
            return
        self._with_user_list(title, lambda users: ManageUserPasswordsDialog(self._store, self, users=users).exec())

    def _open_view_user_portfolio(self) -> None:
        """Admin > View a user's portfolio (read-only window per user)."""
        title = "View a user's portfolio"
        if not self._server_available(title, "view other users' portfolios"):
            return
        self._with_user_list(title, self._pick_user_to_view)

    def _pick_user_to_view(self, users: List[dict]) -> None:
        dlg = SelectUserDialog(users, self._store.user_info["user_id"], self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        user = dlg.selected_user()
        if user is None:
            return
        user_id = user["id"]
        if user_id in self._viewer_windows:
            w = self._viewer_windows[user_id]
            w.raise_()
            w.activateWindow()
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
        # Server /health probe: cheaper than the generic netcheck and gives
        # the server version + latency for the status tooltip. Only started
        # when there is a server to probe.
        self.timer_health = QTimer(self)
        self.timer_health.setInterval(HEALTH_INTERVAL_MS)
        self.timer_health.timeout.connect(self._kick_health_probe)

        if self.L1_ENABLED:
            self.timer_l1.start()
        self.timer_net.start()
        if self._remote_store_for_health() is not None:
            self.timer_health.start()
        # Defer the first ticks so no QThread starts before the QML scene
        # has mounted (Windows access-violation guard).
        QTimer.singleShot(250, self._kick_netcheck)
        QTimer.singleShot(500, self._level1_tick)
        QTimer.singleShot(800, self._kick_health_probe)

    def _busy_enter(self, text: str = "Updating prices…") -> None:
        self._busy_ops += 1
        if self._busy_ops == 1:
            self.spinner.start(90)
        self.lbl_updating.setText(text)
        self.lbl_updating.setToolTip("")

    def _busy_leave(self) -> None:
        self._busy_ops = max(0, self._busy_ops - 1)
        if self._busy_ops == 0:
            self.spinner.stop()
            if self._marks_error:
                self.lbl_updating.setText("Prices not updated")
                self.lbl_updating.setToolTip(
                    f"The last price refresh failed: {self._marks_error}\n"
                    "Prices retry automatically. Press F5 to try now.")
            else:
                self.lbl_updating.setText("")
                self.lbl_updating.setToolTip("")

    def _level1_tick(self) -> None:
        if self._closing or self._marks_flight.is_running():
            return
        # Watchlist + every account's open holdings.
        tickers = list(self._app.watchlist_symbols())
        for account in self._app.accounts:
            tickers.extend(self._holding_symbols(account))
        tickers = [t for t in dict.fromkeys(tickers) if t]
        if not tickers:
            return

        def _wire(worker: MarksWorker) -> None:
            worker.done.connect(self._on_marks)
            worker.error.connect(self._on_marks_error)

        if self._marks_flight.start(MarksWorker(tickers), _wire, on_finished=self._on_marks_finished):
            self._busy_enter()

    @staticmethod
    def _holding_symbols(account) -> List[str]:
        """Open-position symbols for one AccountController.

        AppController has no public accessor for this, so it reads the
        holdings model's private `_rows` (list of dicts with "instrument").
        Keep this the only place that does; replace it if qml_bridge grows
        a public `holding_symbols()`.
        """
        try:
            return [h.get("instrument") for h in account.holdings._rows if h.get("instrument")]
        except AttributeError:
            return []

    def _on_marks_finished(self) -> None:
        if not self._closing:
            self._busy_leave()

    def _on_marks(self, data: dict) -> None:
        if self._closing:
            return
        self._marks_error = None
        self._app.apply_marks(data)

    def _on_marks_error(self, msg: str) -> None:
        # A failed price fetch is not a connectivity verdict (the netcheck
        # owns that); surface it next to the spinner instead.
        if self._closing:
            return
        self._marks_error = msg or "unknown error"

    def _kick_netcheck(self) -> None:
        if self._closing:
            return
        self._netcheck_flight.start(NetCheckWorker(),
                                    lambda worker: worker.done.connect(self._on_net_status))

    def _on_net_status(self, ok: bool) -> None:
        if self._closing:
            return
        self._online = ok
        if not ok:
            pending = self._store.pending_sync_count if isinstance(self._store, FallbackDataStore) else 0
            self._set_connection_state("offline_queued" if pending else "offline", pending)
        elif isinstance(self._store, FallbackDataStore) and not self._store._is_online:
            n = self._store.pending_sync_count
            self._set_connection_state("queued" if n else "server_down", n)
        elif not isinstance(self._store, (RemoteDataStore, FallbackDataStore)):
            self._set_connection_state("local")
        else:
            # Also ends a transient "synced N changes" message.
            self._set_connection_state("online")

    # ── Server health probe ──────────────────────────────────────────
    # Polls /health on a Remote/Fallback store and puts the result in the
    # status tooltip ("Server v1.0.0, 12 ms, database ok, up 2h 14m").

    def _remote_store_for_health(self) -> Optional[RemoteDataStore]:
        """The RemoteDataStore to probe, if any. A FallbackDataStore's remote
        is still addressable while "offline" — a fast failure is useful too."""
        if isinstance(self._store, RemoteDataStore):
            return self._store
        if isinstance(self._store, FallbackDataStore):
            return self._store._remote
        return None

    def _kick_health_probe(self) -> None:
        # Skip while the netcheck says there is no internet at all.
        if self._closing or not self._online:
            return
        remote = self._remote_store_for_health()
        if remote is None:
            return
        self._run_in_background(
            remote.ping_health,
            on_done=self._on_health_result,
            on_error=lambda msg: self._on_health_result({"ok": False, "error": msg}),
            label="ping_health",
        )

    def _on_health_result(self, info: dict) -> None:
        if self._closing or not info:
            return
        if not info.get("ok"):
            err = info.get("error") or "no response"
            self.lbl_status.setToolTip(f"{_SERVER_DOWN_TIP}\nLast check: {err}")
            return
        secs = int(info.get("uptime_seconds", 0) or 0)
        if secs >= 3600:
            uptime = f"{secs // 3600}h {(secs % 3600) // 60}m"
        elif secs >= 60:
            uptime = f"{secs // 60}m {secs % 60}s"
        else:
            uptime = f"{secs}s"
        db_state = "ok" if info.get("db_ok") else "down"
        self.lbl_status.setToolTip(
            f"Sync server v{info.get('server_version', '?')}\n"
            f"Latency: {info.get('latency_ms', '?')} ms\n"
            f"Database: {db_state}\n"
            f"Up for {uptime}"
        )

    def _init_reconnect_timer(self) -> None:
        if not isinstance(self._store, FallbackDataStore):
            return
        self._reconnect_timer_obj = QTimer(self)
        self._reconnect_timer_obj.setInterval(RECONNECT_INTERVAL_MS)
        self._reconnect_timer_obj.timeout.connect(self._attempt_reconnect)
        self._reconnect_timer_obj.start()
        # The store starts offline when a sync queue is left over from the
        # last session; replay it now instead of waiting for the first tick.
        QTimer.singleShot(0, self._attempt_reconnect)

    def _attempt_reconnect(self) -> None:
        if not isinstance(self._store, FallbackDataStore):
            return
        if self._closing or self._store._is_online or self._reconnect_flight.is_running():
            return
        serial_debug("Attempting reconnect to server...")
        self._reconnect_flight.start(ReconnectWorker(self._store),
                                     lambda worker: worker.done.connect(self._on_reconnect_finished))

    def _on_reconnect_finished(self, ok: bool) -> None:
        if ok and not self._closing:
            self._on_reconnected()

    def _on_reconnected(self) -> None:
        if self._closing:
            return
        pending = self._store.pending_sync_count
        self._set_connection_state("syncing" if pending else "online")
        self._app.refresh_all_accounts()

    def _set_offline_status(self, n_pending: int) -> None:
        if self._closing:
            return
        self._set_connection_state("queued" if self._online else "offline_queued", n_pending)

    def _set_synced_status(self, synced_count: int) -> None:
        if self._closing:
            return
        if synced_count > 0:
            self._set_connection_state("synced", synced_count)
        else:
            self._set_connection_state("online")

    # ------------------------------------------------------------------
    # Save / close
    # ------------------------------------------------------------------

    def _save_settings(self, remote: bool = False) -> None:
        """Write device-local preferences to QSettings.

        `remote` is kept for callers that want the watchlist pushed to the
        server too; by default it isn't, because `_save_watchlist` already
        pushes every change in the background and a blocking network call
        here would stall window close by up to the request timeout.
        """
        s = self._qsettings()
        symbols = self._app.watchlist_symbols()
        if remote:
            try:
                self._store.save_watchlist(symbols)
            except Exception:
                get_logger("ui").exception("save_watchlist on close failed")
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
        self.theme.stop_watching()

        for timer_name in ("timer_l1", "timer_net", "timer_health", "_reconnect_timer_obj"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()

        for viewer in list(self._viewer_windows.values()):
            try:
                viewer.close()
            except RuntimeError:  # already destroyed
                pass

        for flight in (self._marks_flight, self._netcheck_flight, self._reconnect_flight):
            flight.shutdown(4000)
        self._bg.shutdown(2000)
        super().closeEvent(event)
