"""Shared Qt widgets used across the application."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QTableWidget,
)


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
        try:
            self.setText("")
        except RuntimeError:
            # C++ object already deleted — nothing to do.
            pass

    def _tick(self) -> None:
        try:
            self.setText(self.FRAMES[self._index % len(self.FRAMES)])
        except RuntimeError:
            self._timer.stop()
            return
        self._index += 1


class WatchTable(QTableWidget):
    """Watchlist table with drag-reorder support and a context menu."""

    fetchRequested = Signal()
    renameRequested = Signal()
    moveRequested = Signal(int)
    sortRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(0, 2, parent)
        self.setObjectName("watchTable")
        self.setHorizontalHeaderLabels(["Ticker", "Mark"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(60)
        if self.horizontalHeaderItem(1) is not None:
            self.horizontalHeaderItem(1).setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        self.verticalHeader().setDefaultSectionSize(30)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setSortingEnabled(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._sort_mode = "Default (custom)"
        self._size_columns()

    def set_sort_mode(self, mode: str) -> None:
        self._sort_mode = str(mode or "Default (custom)")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._size_columns()

    def _size_columns(self) -> None:
        if self.columnCount() < 2:
            return
        self.resizeColumnsToContents()
        available = max(0, self.viewport().width())
        ticker_width = self.columnWidth(0)
        max_ticker_width = max(60, available - 78) if available else 108
        ticker_width = max(72, min(ticker_width + 12, min(108, max_ticker_width)))
        mark_width = max(78, available - ticker_width)
        if available > 0 and ticker_width + mark_width > available:
            mark_width = max(78, available - ticker_width)
        self.setColumnWidth(0, ticker_width)
        self.setColumnWidth(1, mark_width)

    def _show_context_menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if row >= 0:
            self.selectRow(row)

        menu = QMenu(self)
        sort_menu = menu.addMenu("Sort Watchlist")
        for label in ("Default (custom)", "Alphabetical", "Price"):
            action = QAction(label, sort_menu)
            action.setCheckable(True)
            action.setChecked(label == self._sort_mode)
            action.triggered.connect(lambda _checked=False, value=label: self.sortRequested.emit(value))
            sort_menu.addAction(action)

        if self.rowCount() > 0 and self.currentRow() >= 0:
            menu.addSeparator()
            menu.addAction("Rename…", self.renameRequested.emit)
            menu.addSeparator()
            menu.addAction("Move Up", lambda: self.moveRequested.emit(-1))
            menu.addAction("Move Down", lambda: self.moveRequested.emit(+1))
        menu.exec(self.viewport().mapToGlobal(pos))
