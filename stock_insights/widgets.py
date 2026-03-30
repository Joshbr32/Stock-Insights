from __future__ import annotations

"""Shared Qt widgets used across the application.

This module intentionally keeps small reusable widgets isolated from the main
window so they can be reasoned about and tested independently.
"""

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMenu,
    QTableWidget,
    QHeaderView,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class MplCanvas(FigureCanvas):
    """Small matplotlib canvas wrapper used for the price chart."""

    def __init__(self) -> None:
        self.fig = Figure(figsize=(6, 3), tight_layout=True)
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111)


class SpinnerLabel(QLabel):
    """Simple text spinner used while background work is running."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._index = 0

    def start(self, interval_ms: int = 80) -> None:
        self._index = 0
        self._timer.start(interval_ms)

    def stop(self) -> None:
        self._timer.stop()
        self.setText("")

    def _tick(self) -> None:
        self.setText(self.FRAMES[self._index % len(self.FRAMES)])
        self._index += 1


class WatchTable(QTableWidget):
    """Watchlist table with drag-reorder support and a context menu.

    Signals are emitted for actions instead of directly reaching back into the
    main window by method name. This reduces coupling and keeps the widget more
    reusable.
    """

    fetchRequested = Signal()
    renameRequested = Signal()
    moveRequested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["Ticker", "Mark", "Industry"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)

        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setSortingEnabled(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if row >= 0:
            self.selectRow(row)
        if self.rowCount() == 0 or self.currentRow() < 0:
            return

        menu = QMenu(self)
        menu.addAction("Fetch", self.fetchRequested.emit)
        menu.addAction("Rename…", self.renameRequested.emit)
        menu.addSeparator()
        menu.addAction("Move Up", lambda: self.moveRequested.emit(-1))
        menu.addAction("Move Down", lambda: self.moveRequested.emit(+1))
        menu.exec(self.viewport().mapToGlobal(pos))
