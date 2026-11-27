"""Trade history columns + sort order (legacy QWidget PortfolioTab only).

Pick which columns show and up to `max_sort_levels` sort keys. The caller
persists the result (PortfolioTab stores it in QSettings). Read back with
selected_keys() and selected_sort_rules() -> [{"key", "ascending"}].
"""
from __future__ import annotations

from typing import Dict, List

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QGridLayout, QLabel

from ..widgets import Panel, add_dialog_buttons, dialog_layout, set_text_role


class TradeHistoryColumnsDialog(QDialog):
    # Combo *data* for an unused sort level; never persisted.
    NONE_SORT_LABEL = "(Not used)"
    _NONE_TEXT = "Not used"

    def __init__(self, columns: List[tuple], visible_keys: List[str], sort_rules: List[dict],
                 max_sort_levels: int = 5, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trade history columns")
        self.setMinimumWidth(440)
        root = dialog_layout(self)

        show = Panel("Show columns")
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self._checks: Dict[str, QCheckBox] = {}
        half = (len(columns) + 1) // 2
        for i, (key, label) in enumerate(columns):
            cb = QCheckBox(label)
            cb.setChecked(key in visible_keys)
            self._checks[key] = cb
            grid.addWidget(cb, i % half, i // half)
        show.body.addLayout(grid)
        root.addWidget(show)

        sort = Panel("Sort by", subtitle="Rows sort by the first column, then the next to break ties.")
        sort_grid = QGridLayout()
        sort_grid.setHorizontalSpacing(8)
        sort_grid.setVerticalSpacing(8)
        sort_grid.setColumnStretch(1, 1)
        self._sort_controls: List[tuple] = []
        for row in range(max_sort_levels):
            num = QLabel("Then" if row else "First")
            set_text_role(num, "muted")
            column_combo = QComboBox()
            column_combo.addItem(self._NONE_TEXT, self.NONE_SORT_LABEL)
            for key, label in columns:
                column_combo.addItem(label, key)
            direction_combo = QComboBox()
            direction_combo.addItem("Ascending", True)
            direction_combo.addItem("Descending", False)
            if row < len(sort_rules):
                rule = sort_rules[row]
                index = column_combo.findData(str(rule.get("key", self.NONE_SORT_LABEL)))
                column_combo.setCurrentIndex(max(0, index))
                d_index = direction_combo.findData(bool(rule.get("ascending", True)))
                direction_combo.setCurrentIndex(max(0, d_index))
            sort_grid.addWidget(num, row, 0)
            sort_grid.addWidget(column_combo, row, 1)
            sort_grid.addWidget(direction_combo, row, 2)
            self._sort_controls.append((column_combo, direction_combo))
        sort.body.addLayout(sort_grid)
        root.addWidget(sort)

        root.addStretch(1)
        add_dialog_buttons(self, root, "Save")

    def selected_keys(self) -> List[str]:
        return [key for key, cb in self._checks.items() if cb.isChecked()]

    def selected_sort_rules(self) -> List[dict]:
        rules: List[dict] = []
        seen = set()
        for column_combo, direction_combo in self._sort_controls:
            key = column_combo.currentData()
            if key == self.NONE_SORT_LABEL or key in seen:
                continue
            seen.add(key)
            rules.append({"key": str(key), "ascending": bool(direction_combo.currentData())})
        return rules
