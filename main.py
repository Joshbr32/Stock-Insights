import sys
from PySide6.QtWidgets import QApplication
from stock_insights.connection_dialog import ConnectionDialog
from stock_insights.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Stock Insights")
    app.setOrganizationName("StockInsights")

    dlg = ConnectionDialog()
    store = dlg.run()

    if store is None:
        sys.exit(0)

    win = MainWindow(store)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()