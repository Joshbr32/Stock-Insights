"""Render the QML scene at three different window widths (narrow, medium,
wide) and verify every column in both tables stays inside the viewport."""
import os
import sys
from datetime import date
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ".")

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from stock_insights.portfolio import Trade
from stock_insights.qml_bridge import AppController


class FakeStore:
    username = "stub"
    is_admin = False
    _trades = [
        Trade("NVDA", 100, 450.0, sell_price=470.0,
              open_date=date(2026, 1, 5), close_date=date(2026, 1, 20),
              notes="", account="Josh"),
        Trade("AAPL", 50, 180.0, sell_price=195.0,
              open_date=date(2026, 1, 8), close_date=date(2026, 1, 18),
              notes="", account="Josh"),
        Trade("TSLA", 30, 240.0, sell_price=210.0,
              open_date=date(2026, 2, 1), close_date=date(2026, 2, 15),
              notes="", account="Josh"),
        Trade("GOOG", 10, 140.0, open_date=date(2026, 4, 1),
              notes="", account="Josh"),
    ]

    def get_account_names(self): return ["Josh"]

    def get_all_trades(self): return list(self._trades)

    def get_goal_group(self): return ([], 500_000.0)

    def get_goal_target(self, n): return 500_000.0

    def get_goal_presets(self, n): return [250_000.0, 500_000.0, 1_000_000.0]

    def get_watchlist(self): return ["NVDA"]


class FakeTheme(QObject):
    themeApplied = Signal()
    theme_name = "Default"

    def __init__(self): super().__init__()

    def _tokens(self): return None

    def _is_light(self): return False


def measure(w):
    """Return total width-of-children vs ListView-viewport-width for every
    ListView, plus per-table column widths."""
    out = []
    for c in w.rootObject().findChildren(QObject):
        if not hasattr(c, "metaObject"):
            continue
        if c.metaObject().className() != "QQuickListView":
            continue
        list_w = c.property("width") or 0
        cnt = c.property("count") or 0
        # Find the first delegate Rectangle and sum its Label widths
        # (skip overlay rectangles which have no Labels)
        first_delegate = None
        for child in c.findChildren(QObject):
            ccn = child.metaObject().className() if hasattr(child, "metaObject") else ""
            if ccn != "QQuickRectangle":
                continue
            if (child.property("width") or 0) < 100:  # overlay tints / scrollbar
                continue
            # A delegate row contains Labels — skip if not
            label_widths = [
                round(g.property("width") or 0)
                for g in child.findChildren(QObject)
                if hasattr(g, "metaObject")
                   and g.metaObject().className() == "QQuickLabel"
                   and (g.property("width") or 0) >= 5
            ]
            if not label_widths:
                continue
            first_delegate = (round(child.property("width") or 0), label_widths)
            break
        out.append({
            "list_w": list_w,
            "count": cnt,
            "delegate": first_delegate,
        })
    return out


def main():
    app = QApplication(sys.argv)
    ctrl = AppController(FakeStore(), FakeTheme())
    ctrl.rebuild_accounts()
    ctrl.refresh_all_accounts()

    w = QQuickWidget()
    w.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
    w.engine().rootContext().setContextProperty("app", ctrl)
    qml = Path("stock_insights/qml/Main.qml").resolve()
    w.setSource(QUrl.fromLocalFile(str(qml)))
    if w.status() == QQuickWidget.Status.Error:
        for e in w.errors():
            print("QML ERROR:", e)
        return 1

    for size in [(1500, 950), (1200, 800), (900, 700)]:
        w.resize(*size)
        w.show()
        for _ in range(5):
            app.processEvents()
        print(f"\n══ Window {size[0]}x{size[1]} ══")
        for entry in measure(w):
            d = entry["delegate"]
            if d:
                row_w, labels = d
                total = sum(labels)
                fits = "✓ FITS" if total <= row_w + 1 else f"✗ OVERFLOW by {total - row_w}px"
                print(f"  ListView w={entry['list_w']:.0f}  count={entry['count']}  "
                      f"row w={row_w}  Σ labels={total}  {fits}")
                print(f"    columns: {labels}")
            else:
                print(f"  ListView w={entry['list_w']:.0f}  count={entry['count']}  (no delegates)")

        img = w.grab()
        img.save(f"_qml_fit_{size[0]}.png")

    return 0


if __name__ == "__main__":
    sys.exit(main())
