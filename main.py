"""main.py — Entry point for Stock Insights."""

import os
import sys

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication, QWidget

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)

from stock_insights.connection_dialog import ConnectionDialog
from stock_insights.main_window import MainWindow
from stock_insights.theme import ThemeManager


def _apply_startup_theme() -> None:
    """Read saved theme settings and apply them to QApplication before any
    window is shown, so the ConnectionDialog uses the correct theme."""
    s = QSettings("StockInsights", "StocksGUI")

    # ThemeManager needs a QObject/QWidget parent; a throwaway QWidget is fine
    # because apply() installs palette + stylesheet on QApplication.instance().
    dummy = QWidget()
    tm = ThemeManager(dummy)
    tm.override_mode = s.value("ui/THEME_OVERRIDE", "System")
    tm.match_system_accent = s.value("ui/MATCH_SYSTEM_ACCENT", True, type=bool)
    tm.theme_name = s.value("ui/THEME_NAME", "Default")
    tm.font_size_label = s.value("ui/FONT_SIZE", "Normal")
    tm.apply()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Stock Insights")
    app.setOrganizationName("StockInsights")

    _apply_startup_theme()

    dlg = ConnectionDialog()
    store = dlg.run()

    if store is None:
        sys.exit(0)

    window = MainWindow(store)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
