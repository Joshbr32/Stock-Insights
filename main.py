
from PySide6.QtWidgets import QApplication
import sys
from stock_insights.main_window import MainWindow
from stock_insights.logging_utils import serial_debug

def main():
    app = QApplication(sys.argv)
    app.setOrganizationName(MainWindow.ORG)
    app.setApplicationName(MainWindow.APP)
    serial_debug("QApplication created; constructing MainWindow")
    win = MainWindow()
    serial_debug("MainWindow constructed")
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
