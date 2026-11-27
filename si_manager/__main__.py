"""Entry point: ``python -m si_manager`` (from the repository root)."""
import sys

from PySide6.QtWidgets import QApplication

from si_controller.client import Client

from . import APP_NAME, theme
from .window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    theme.apply(app)
    window = MainWindow(Client())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
