"""main.py — Entry point for Stock Insights."""

import os
import sys

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)

from stock_insights.connection_dialog import ConnectionDialog
from stock_insights.main_window import MainWindow
from stock_insights.theme import ThemeManager


def _apply_startup_theme(app: QApplication) -> None:
    """Read saved theme settings and apply them to QApplication before any
    window is shown, so the ConnectionDialog uses the correct theme."""
    s = QSettings("StockInsights", "StocksGUI")

    # Build a minimal QObject to host ThemeManager (it needs a parent window,
    # but we can pass the app itself — it only uses win.setStyleSheet / setPalette
    # which are no-ops on QApplication, so we use a throwaway QWidget instead)
    from PySide6.QtWidgets import QWidget
    dummy = QWidget()

    tm = ThemeManager(dummy)
    tm.override_mode   = s.value("ui/THEME_OVERRIDE",   "System")
    tm.match_system_accent = s.value("ui/MATCH_SYSTEM_ACCENT", True, type=bool)
    tm.theme_name      = s.value("ui/THEME_NAME",        "Default")
    tm.font_size_label = s.value("ui/FONT_SIZE",         "Normal")
    tm.apply()   # applies palette + stylesheet to QApplication.instance()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Stock Insights")
    app.setOrganizationName("StockInsights")

    _apply_startup_theme(app)

    dlg = ConnectionDialog()
    store = dlg.run()

    if store is None:
        sys.exit(0)

    window = MainWindow(store)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
