"""Render every QWidget dialog/window to PNG for visual review.

Usage:
    python scripts/ui_snapshot_dialogs.py --out <folder> [--themes Default,Forest] [--modes light,dark]
                                          [--only settings,trade_new]

What it does
    * Opens each desktop dialog (login, settings, admin dialogs, trade dialogs,
      symbol history, the main window's menu bar + status corner) with fixture
      data from an in-memory fake store.
    * Applies the theme through ThemeManager in each requested theme/mode.
    * Saves `<out>/<theme>-<mode>/<name>.png` via QWidget.grab().

Isolation guarantees (so it is safe to run on a developer machine)
    * NO network: every socket connect raises, workers that fetch prices are
      never started, and stores are fakes.
    * QSettings is redirected to an INI file in a temp dir under a distinct
      organisation name, *before* any stock_insights module is imported, so the
      user's real QSettings("StockInsights", "StocksGUI") is never read or written.
    * The launch auto-snapshot (~/.stock_insights/auto_backups) is disabled.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


# ---------------------------------------------------------------------------
# 1. Block the network before anything else can open a connection.
# ---------------------------------------------------------------------------

def _no_network(*_args, **_kwargs):
    raise OSError("network disabled by ui_snapshot_dialogs.py")


socket.create_connection = _no_network  # type: ignore[assignment]
socket.socket.connect = _no_network  # type: ignore[assignment]
socket.socket.connect_ex = _no_network  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 2. Redirect QSettings to a private INI file under a distinct organisation.
#    Must happen before `stock_insights` is imported: modules bind the name
#    with `from PySide6.QtCore import QSettings` at import time.
# ---------------------------------------------------------------------------

from PySide6 import QtCore  # noqa: E402

_SANDBOX_DIR = Path(tempfile.mkdtemp(prefix="si_ui_snapshot_"))
_SANDBOX_ORG = "StockInsightsUISnapshot"
_RealQSettings = QtCore.QSettings


class _SandboxSettings(_RealQSettings):
    """Every construction form maps to one throwaway INI file."""

    def __init__(self, *_args, **_kwargs):
        super().__init__(str(_SANDBOX_DIR / f"{_SANDBOX_ORG}.ini"), _RealQSettings.Format.IniFormat)


_RealQSettings.setPath(_RealQSettings.Format.IniFormat, _RealQSettings.Scope.UserScope, str(_SANDBOX_DIR))
QtCore.QSettings = _SandboxSettings  # type: ignore[misc]
QtCore.QCoreApplication.setOrganizationName(_SANDBOX_ORG)
QtCore.QCoreApplication.setApplicationName("Snapshots")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget  # noqa: E402

QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

from stock_insights.api_client import DataStore  # noqa: E402
from stock_insights.portfolio import Holding, Trade  # noqa: E402
from stock_insights.theme import THEME_NAMES, ThemeManager  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TODAY = date.today()


def _d(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


def fixture_trades() -> list:
    return [
        Trade("NVDA", 100, 120.50, 131.25, _d(60), _d(41), "Earnings run-up", "Main", tag="earnings"),
        Trade("NVDA", 50, 128.00, 119.40, _d(35), _d(30), "", "Main", tag="swing"),
        Trade("NVDA", 80, 125.10, None, _d(12), None, "Add on dip", "Main"),
        Trade("NVDA", 40, 118.00, 112.10, _d(25), _d(20), "", "Main", tag="swing"),
        Trade("RDDT", 200, 64.20, None, _d(20), None, "", "Main"),
        Trade("CCL", 300, 18.40, None, _d(9), None, "", "Main"),
        Trade("TSLA", 20, 248.00, None, None, None, "Limit order", "Main", is_pending=True),
        Trade("SRPT", 30, 92.00, 99.50, _d(15), _d(4), "", "Main", is_short=True),
        Trade("FIG", 60, 31.00, None, _d(5), None, "", "Main", is_short=True),
        Trade("NCLH", 150, 19.10, 22.40, _d(90), _d(70), "", "Roth"),
        Trade("AAPL", 25, 190.00, None, _d(40), None, "", "Roth"),
    ]


FIXTURE_MARKS = {
    "NVDA": {"price": 127.80, "change_pct": 1.2},
    "RDDT": {"price": 71.05, "change_pct": -0.8},
    "CCL": {"price": 17.95, "change_pct": 0.3},
    "FIG": {"price": 29.10, "change_pct": -2.1},
    "AAPL": {"price": 201.30, "change_pct": 0.4},
}

FIXTURE_USERS = [
    {"id": 1, "username": "josh", "is_admin": True},
    {"id": 2, "username": "narmeen", "is_admin": False},
    {"id": 3, "username": "sam", "is_admin": False},
    {"id": 4, "username": "alex", "is_admin": True},
]


class FakeStore(DataStore):
    """In-memory DataStore. Never touches disk or network."""

    def __init__(self, username: str = "josh", is_admin: bool = True):
        self._trades = fixture_trades()
        self._accounts = ["Main", "Roth"]
        self._goals = {"Main": 100_000.0, "Roth": 25_000.0}
        self._presets = {"Main": [50_000.0, 100_000.0, 250_000.0], "Roth": [10_000.0, 25_000.0, 50_000.0]}
        self._group = (["Main"], 100_000.0)
        self._watchlist = ["NVDA", "RDDT", "CCL", "FIG", "NCLH", "SRPT"]
        self._info = {"user_id": 1, "username": username, "is_admin": is_admin}

    def get_all_trades(self):
        return list(self._trades)

    def save_account_trades(self, account_name, trades):
        self._trades = [t for t in self._trades if t.account != account_name] + list(trades)

    def get_account_names(self):
        return list(self._accounts)

    def save_accounts(self, accounts):
        self._accounts = list(accounts)

    def get_goal_target(self, account_name):
        return self._goals.get(account_name, 500_000.0)

    def set_goal_target(self, account_name, value):
        self._goals[account_name] = float(value)

    def get_goal_presets(self, account_name):
        return list(self._presets.get(account_name, [250_000.0, 500_000.0, 1_000_000.0]))

    def set_goal_presets(self, account_name, presets):
        self._presets[account_name] = list(presets)

    def get_goal_group(self):
        return self._group

    def set_goal_group(self, shared_accounts, shared_goal, individual_goals, all_presets=None):
        self._group = (list(shared_accounts), float(shared_goal))

    def get_watchlist(self):
        return list(self._watchlist)

    def save_watchlist(self, symbols):
        self._watchlist = list(symbols)

    @property
    def user_info(self):
        return self._info

    def list_users(self):
        return list(FIXTURE_USERS)

    def store_for_user(self, _user_id, username):
        return FakeStore(username, is_admin=False)


# ---------------------------------------------------------------------------
# Scenes: each returns a top-level widget to grab (already constructed).
# ---------------------------------------------------------------------------

def scene_connection(host):
    from stock_insights.connection_dialog import ConnectionDialog
    dlg = ConnectionDialog(host)
    dlg.user_edit.setText("josh")
    return dlg


def scene_connection_error(host):
    dlg = scene_connection(host)
    msg = "Can't reach the sync server."
    shower = getattr(dlg, "_show_error", None)
    if callable(shower):
        shower(msg)
    else:  # pre-redesign fallback
        dlg.status_label.setText(msg)
        dlg.debug_box.setVisible(True)
    dlg._log("Checking TCP example.invalid:443 ...")
    dlg._log("Port 443 not reachable.")
    return dlg


def scene_settings(host):
    from stock_insights.settings_dialog import SettingsDialog
    cv = {"L1_INTERVAL": 20_000, "NET_INTERVAL": 10_000, "L1_ENABLED": True, "THEME_OVERRIDE": "System",
          "MATCH_SYSTEM_ACCENT": True, "THEME_NAME": "Default", "FONT_SIZE": "Normal",
          "TRADE_DEFAULT_QUANTITY": 100, "TRADE_QUANTITY_INCREMENT": 10}
    return SettingsDialog(host, QtCore.QSettings(), cv)


def scene_user_account(host):
    from stock_insights.admin_dialogs import UserAccountDialog
    return UserAccountDialog(FakeStore(), host)


def scene_select_user(host):
    from stock_insights.admin_dialogs import SelectUserDialog
    dlg = SelectUserDialog(FIXTURE_USERS, 1, host)
    dlg.list_widget.setCurrentRow(0)
    return dlg


def scene_manage_passwords(host):
    from stock_insights import admin_dialogs
    try:
        return admin_dialogs.ManageUserPasswordsDialog(FakeStore(), host, users=FIXTURE_USERS)
    except TypeError:  # pre-redesign signature
        return admin_dialogs.ManageUserPasswordsDialog(FakeStore(), host)


def scene_user_portfolio_viewer(host):
    from stock_insights import admin_dialogs
    admin_dialogs.UserPortfolioViewer._refresh_marks = lambda self: None  # never fetch prices
    viewer = admin_dialogs.UserPortfolioViewer(FakeStore("narmeen", False), "narmeen", QtCore.QSettings(),
                                               parent=None)
    viewer._on_marks(FIXTURE_MARKS)
    viewer.resize(1100, 760)
    return viewer


def scene_symbol_history(host):
    from stock_insights.symbol_history_dialog import SymbolHistoryDialog
    return SymbolHistoryDialog("NVDA", fixture_trades(), current_mark=127.80, parent=host)


def scene_symbol_history_empty(host):
    from stock_insights.symbol_history_dialog import SymbolHistoryDialog
    return SymbolHistoryDialog("RDDT", fixture_trades(), current_mark=None, parent=host)


def _trade_dialog(host, **kw):
    from stock_insights.dialogs import TradeEditDialog
    return TradeEditDialog(watchlist_symbols=["NVDA", "RDDT", "CCL"], default_quantity=100,
                           quantity_increment=10, parent=host, **kw)


def scene_trade_new(host):
    return _trade_dialog(host)


def scene_trade_edit_closed(host):
    return _trade_dialog(host, trade=fixture_trades()[0])


def scene_trade_pending(host):
    return _trade_dialog(host, trade=fixture_trades()[6])


def scene_trade_close_position(host):
    t = Trade("NVDA", 80, 125.10, None, _d(12), None, "Add on dip", "Main")
    dlg = _trade_dialog(host, trade=t, close_holdings_mode=True)
    dlg.sell_price_spin.setValue(131.40)
    return dlg


def scene_trade_cover(host):
    t = Trade("FIG", 60, 31.00, None, _d(5), None, "", "Main", is_short=True)
    dlg = _trade_dialog(host, trade=t, cover_mode=True)
    dlg.sell_price_spin.setValue(29.10)
    return dlg


def scene_fulfill(host):
    from stock_insights.dialogs import FulfillOrderDialog
    return FulfillOrderDialog(fixture_trades()[6], host)


def scene_mark_down(host):
    from stock_insights.dialogs import MarkDownDialog
    dlg = MarkDownDialog(Holding("NVDA", 80, 125.10), default_quantity=100, quantity_increment=10, parent=host)
    dlg.target_avg_spin.setValue(121.00)
    return dlg


def scene_mark_down_impossible(host):
    dlg = scene_mark_down(host)
    dlg.buy_qty_spin.setValue(10)
    dlg.target_avg_spin.setValue(60.00)
    return dlg


def scene_double_down(host):
    from stock_insights.dialogs import DoubleDownDialog
    return DoubleDownDialog(Holding("NVDA", 80, 125.10), current_mark=127.80, quantity_increment=10, parent=host)


def scene_goal_options(host):
    from stock_insights.dialogs import GoalDashboardOptionsDialog
    s = FakeStore()
    accounts = s.get_account_names()
    return GoalDashboardOptionsDialog(accounts, ["Main"], s._goals, s._presets, host)


def scene_trade_history_columns(host):
    from stock_insights.dialogs import TradeHistoryColumnsDialog
    from stock_insights.portfolio_tab import PortfolioTab
    cols = PortfolioTab.TRADE_HISTORY_COLUMNS
    return TradeHistoryColumnsDialog(cols, [k for k, _ in cols][:7],
                                     [{"key": "close_date", "ascending": False},
                                      {"key": "instrument", "ascending": True}], parent=host)


SCENES = {name[len("scene_"):]: fn for name, fn in list(globals().items()) if name.startswith("scene_")}


# ---------------------------------------------------------------------------
# Main window (menu bar + status corner) — built once per theme/mode.
# ---------------------------------------------------------------------------

def build_main_window():
    from stock_insights import main_window as mw
    # No timers (marks/net/health/reconnect would start threads and fetch),
    # no launch auto-snapshot (writes to the user's home directory).
    mw.MainWindow._init_timers = lambda self: None
    mw.MainWindow._init_reconnect_timer = lambda self: None
    mw.MainWindow._write_launch_snapshot = lambda self: None
    mw.setup_logging = lambda *a, **k: None  # keep the user's app.log clean
    win = mw.MainWindow(FakeStore())
    win.theme.stop_watching()
    try:
        win._app.apply_marks(FIXTURE_MARKS)
    except Exception:
        pass
    return win


def _set_status(win, state: str) -> None:
    setter = getattr(win, "_set_connection_state", None)
    if callable(setter):
        setter(state, 3)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _settle(app, widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    for _ in range(4):
        app.processEvents()
    widget.adjustSize() if not isinstance(widget, QMainWindow) else None
    for _ in range(4):
        app.processEvents()


def _theme_for(host, theme: str, mode: str) -> ThemeManager:
    tm = getattr(host, "theme", None)
    if not isinstance(tm, ThemeManager):
        tm = ThemeManager(host)
        host.theme = tm
    tm.stop_watching()
    tm.match_system_accent = False
    tm.theme_name = theme
    tm.override_mode = "Light" if mode == "light" else "Dark"
    tm.apply()
    return tm


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="Folder for PNGs (created if missing)")
    ap.add_argument("--themes", default="Default", help=f"Comma list or 'all'. Known: {', '.join(THEME_NAMES)}")
    ap.add_argument("--modes", default="light,dark")
    ap.add_argument("--only", default="", help="Comma list of scene names (plus 'main_window')")
    ap.add_argument("--list", action="store_true", help="List scene names and exit")
    args = ap.parse_args()

    names = list(SCENES) + ["main_window"]
    if args.list:
        print("\n".join(names))
        return 0
    wanted = [n.strip() for n in args.only.split(",") if n.strip()] or names
    themes = THEME_NAMES if args.themes == "all" else [t.strip() for t in args.themes.split(",") if t.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    app = QApplication.instance() or QApplication(sys.argv)
    out_root = Path(args.out)
    failures = 0

    main_win = build_main_window() if "main_window" in wanted else None
    host = main_win or QMainWindow()

    for theme in themes:
        for mode in modes:
            folder = out_root / f"{theme.replace(' ', '_')}-{mode}"
            folder.mkdir(parents=True, exist_ok=True)
            _theme_for(host, theme, mode)

            if main_win is not None:
                _set_status(main_win, "offline")
                main_win.resize(1280, 860)
                _settle(app, main_win)
                main_win.grab().save(str(folder / "main_window.png"))
                main_win.menuBar().grab().save(str(folder / "main_window_menubar.png"))

            for name in wanted:
                if name == "main_window":
                    continue
                try:
                    widget = SCENES[name](host)
                    _settle(app, widget)
                    widget.grab().save(str(folder / f"{name}.png"))
                    widget.close()
                    widget.deleteLater()
                except Exception as exc:  # keep going; report at the end
                    failures += 1
                    print(f"[{theme}-{mode}] {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                app.processEvents()
            print(f"wrote {folder}")

    if main_win is not None:
        main_win._closing = True
        main_win.hide()
    shutil.rmtree(_SANDBOX_DIR, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
