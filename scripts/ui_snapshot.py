"""ui_snapshot.py — render the real desktop QML scene to PNGs, offline.

Boots ``stock_insights/qml/Main.qml`` with the real ``AppController`` and
``ThemeManager`` on a fixed fixture (2 accounts, ~40 trades covering open,
closed, short, covered and pending, a goal and a watchlist) and saves PNGs
of the main view in light and dark mode at 1440x900 and 1100x700.

Isolation guarantees (so it is safe to run on a dev machine):
  * No network: marks are a fixed price table applied through
    ``AppController.apply_marks``; Python sockets are disabled outright.
  * No real settings: QSettings defaults are redirected to a temp dir with a
    distinct organisation name, and the data store writes to an explicit
    INI file in that temp dir (``LocalDataStore`` would otherwise use the
    registry under the real "StockInsights" organisation).

Usage:
    .venv/Scripts/python.exe scripts/ui_snapshot.py --out <folder>
    [--sizes 1440x900,1100x700] [--modes light,dark] [--theme Default]
    [--account N] [--empty-account] [--hide-curve]
"""

from __future__ import annotations

import argparse
import random
import socket
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _block_network() -> None:
    """Fail loudly if anything in-process tries to open a socket."""

    def _refuse(*_a, **_k):
        raise RuntimeError("ui_snapshot: network access is disabled")

    socket.socket.connect = _refuse  # type: ignore[assignment]
    socket.create_connection = _refuse  # type: ignore[assignment]


_block_network()

from PySide6 import QtCharts  # noqa: E402,F401  (registers the QtCharts QML module)
from PySide6.QtCore import (QCoreApplication, QEventLoop, QSettings, QTimer, QUrl, Qt,  # noqa: E402
                            QtMsgType, qInstallMessageHandler)
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtQuickWidgets import QQuickWidget  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from stock_insights.api_client import LocalDataStore  # noqa: E402
from stock_insights.portfolio import Trade  # noqa: E402
from stock_insights.qml_bridge import AppController  # noqa: E402
from stock_insights.theme import ThemeManager  # noqa: E402

QML_MAIN = ROOT / "stock_insights" / "qml" / "Main.qml"
SNAPSHOT_ORG = "StockInsightsSnapshot"

# Fixed marks — no yfinance. Symbols not listed here render as "no price".
PRICES = {
    "NVDA": 181.40, "AAPL": 231.15, "MSFT": 512.30, "AMD": 164.85,
    "TSLA": 342.10, "PLTR": 158.20, "SOFI": 24.65, "RDDT": 212.55,
    "NCLH": 22.80, "CCL": 29.15, "SHOP": 151.70, "COIN": 318.40,
    "META": 702.25, "SRPT": 14.60, "HOOD": 128.35,
}


class FixtureStore(LocalDataStore):
    """LocalDataStore pinned to an explicit INI file in a temp dir."""

    ORG = SNAPSHOT_ORG

    def __init__(self, ini_path: Path, username: str = "snapshot"):
        # super() sets up locks/prefixes; its QSettings(ORG, APP) ignores
        # setDefaultFormat (it is always native), so it is swapped for an
        # explicit INI file before anything is read or written. ORG is the
        # distinct snapshot organisation, so even that handle is not the
        # user's real "StockInsights" settings.
        super().__init__(username)
        self._settings = QSettings(str(ini_path), QSettings.Format.IniFormat)


def _fixture_trades(today: date) -> list[Trade]:
    """~40 deterministic trades, dated relative to `today` so the goal pace
    and date-range filters always have something sensible to show."""
    rng = random.Random(7)
    jan1 = date(today.year, 1, 1)
    span = max(30, (today - jan1).days)
    syms = ["NVDA", "AAPL", "MSFT", "AMD", "TSLA", "PLTR", "SOFI", "SHOP", "COIN", "META", "HOOD"]
    tags = ["swing", "earnings", "momentum", ""]
    out: list[Trade] = []

    # Closed longs spread across the year for the main account.
    for i in range(24):
        sym = syms[i % len(syms)]
        opened = jan1 + timedelta(days=int(span * i / 26) + rng.randint(0, 3))
        held = rng.randint(2, 18)
        closed = min(today - timedelta(days=1), opened + timedelta(days=held))
        base = PRICES[sym] * rng.uniform(0.7, 1.0)
        move = rng.uniform(-0.06, 0.12)
        qty = rng.choice([20, 40, 50, 75, 100, 150])
        out.append(Trade(sym, qty, round(base, 2), round(base * (1 + move), 2),
                         opened, closed, account="Main", tag=rng.choice(tags)))
    # Closed shorts (covered).
    for sym, qty, entry, cover, d in [("TSLA", 30, 288.0, 251.5, 120), ("COIN", 25, 301.0, 322.4, 60)]:
        out.append(Trade(sym, qty, entry, cover, today - timedelta(days=d + 9),
                         today - timedelta(days=d), account="Main", is_short=True, tag="swing"))
    # Open longs + one open short + pending orders.
    out += [
        Trade("NVDA", 120, 168.20, None, today - timedelta(days=12), account="Main", tag="momentum"),
        Trade("PLTR", 200, 149.80, None, today - timedelta(days=8), account="Main"),
        Trade("AMD", 80, 171.30, None, today - timedelta(days=5), account="Main", notes="Adding on dips"),
        Trade("SOFI", 600, 22.10, None, today - timedelta(days=20), account="Main"),
        Trade("RDDT", 40, 224.00, None, today - timedelta(days=3), account="Main", is_short=True),
        Trade("SHOP", 60, 145.00, None, today, account="Main", is_pending=True, notes="Limit buy"),
    ]
    # Second account: a smaller, slower IRA.
    for i, (sym, qty, b, s) in enumerate([("MSFT", 15, 455.0, 498.2), ("AAPL", 40, 214.0, 226.9),
                                          ("META", 10, 640.0, 611.5), ("HOOD", 100, 88.0, 117.4),
                                          ("AAPL", 30, 205.5, 229.0)]):
        opened = jan1 + timedelta(days=30 + i * 55)
        out.append(Trade(sym, qty, b, s, opened, opened + timedelta(days=21), account="Roth IRA", tag="long-term"))
    out += [
        Trade("MSFT", 20, 497.0, None, today - timedelta(days=30), account="Roth IRA"),
        Trade("META", 8, 688.0, None, today - timedelta(days=14), account="Roth IRA"),
        Trade("NVDA", 25, 176.0, None, today, account="Roth IRA", is_pending=True),
    ]
    return out


def _seed_store(store: FixtureStore, today: date) -> None:
    store.save_accounts(["Main", "Roth IRA"])
    trades = _fixture_trades(today)
    for name in ("Main", "Roth IRA"):
        store.save_account_trades(name, [t for t in trades if t.account == name])
    store.set_goal_target("Main", 5_000.0)
    store.set_goal_presets("Main", [2_500.0, 5_000.0, 10_000.0])
    store.set_goal_target("Roth IRA", 4_800.0)
    store.set_goal_presets("Roth IRA", [3_000.0, 4_800.0, 6_000.0])
    store.save_watchlist(["NVDA", "AAPL", "MSFT", "AMD", "TSLA", "PLTR", "RDDT", "NCLH", "CCL", "SRPT", "XYZQ"])


def _qt_messages(mode, _ctx, msg) -> None:
    """Echo QML warnings/errors so layout or binding problems are visible."""
    if mode != QtMsgType.QtDebugMsg:
        print(f"[qt] {msg}", file=sys.stderr)


def _pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="folder to write PNGs into")
    ap.add_argument("--sizes", default="1440x900,1100x700")
    ap.add_argument("--modes", default="light,dark")
    ap.add_argument("--theme", default="Default", help="theme name from theme.THEME_NAMES")
    ap.add_argument("--account", type=int, default=0, help="account tab index to show")
    ap.add_argument("--empty-account", action="store_true",
                    help="add a third account with no trades (to check empty states)")
    ap.add_argument("--hide-curve", action="store_true", help="render with the equity curve hidden")
    args = ap.parse_args(argv)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="si_snapshot_"))

    # Redirect every QSettings default into the temp dir, under a distinct
    # organisation, before the QApplication exists.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(tmp))
    QCoreApplication.setOrganizationName(SNAPSHOT_ORG)
    QCoreApplication.setApplicationName("UiSnapshot")

    qInstallMessageHandler(_qt_messages)
    app = QApplication.instance() or QApplication([sys.argv[0]])

    today = date.today()
    store = FixtureStore(tmp / "store.ini")
    _seed_store(store, today)
    if args.empty_account:
        store.save_accounts(["Main", "Roth IRA", "New account"])

    host = QWidget()
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)

    theme = ThemeManager(host)
    theme.match_system_accent = False
    theme.theme_name = args.theme
    theme.font_size_label = "Normal"

    ctrl = AppController(store, theme, host)
    ctrl.rebuild_accounts()
    ctrl.refresh_all_accounts()  # MainWindow does this before mounting QML
    ctrl.set_watchlist(store.get_watchlist())
    ctrl.apply_marks({s: {"price": p} for s, p in PRICES.items()})
    ctrl.setCurrentAccountIndex(args.account)
    ctrl.set_equity_curve_visible(not args.hide_curve)
    theme.themeApplied.connect(ctrl.theme.refresh)

    view = QQuickWidget()
    view.engine().rootContext().setContextProperty("app", ctrl)
    view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    view.setClearColor(QColor(0, 0, 0, 0))
    view.setSource(QUrl.fromLocalFile(str(QML_MAIN)))
    if view.status() == QQuickWidget.Status.Error:
        for e in view.errors():
            print("QML error:", e.toString(), file=sys.stderr)
        return 1
    lay.addWidget(view)

    sizes = [tuple(int(v) for v in s.lower().split("x")) for s in args.sizes.split(",") if s]
    modes = [m.strip().lower() for m in args.modes.split(",") if m.strip()]
    written = []
    host.show()
    for mode in modes:
        theme.set_override_mode("Light" if mode == "light" else "Dark")
        for w, h in sizes:
            host.resize(w, h)
            _pump(900)  # layout + the one-shot pace-rail animation (400 ms)
            img = view.grabFramebuffer()
            suffix = "" if args.theme == "Default" else "-" + args.theme.lower().replace(" ", "-")
            if args.account:
                suffix += f"-account{args.account}"
            path = out_dir / f"main-{mode}-{w}x{h}{suffix}.png"
            img.save(str(path))
            written.append(path)
            print(path)
    # Unload QML before the controller goes away, so bindings don't
    # evaluate against a null `app` during teardown.
    view.setSource(QUrl())
    host.close()
    app.processEvents()
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
