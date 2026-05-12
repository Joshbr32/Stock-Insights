"""Trade History column-visibility + sort-order configuration dialog.

User-facing customization for which columns appear in the QML
TradesTable and in what default sort order. State persists per-user
via QSettings.
"""
from __future__ import annotations

from typing import List

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)


# ---------------------------------------------------------------------------
# Trade History Columns dialog
# ---------------------------------------------------------------------------

class TradeHistoryColumnsDialog(QDialog):
    NONE_SORT_LABEL = "(Not used)"

    def __init__(
            self,
            columns: List[tuple],
            visible_keys: List[str],
            sort_rules: List[dict],
            max_sort_levels: int = 5,
            parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Trade History Settings")
        self.resize(420, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._checks: Dict[str, QCheckBox] = {}
        for key, label in columns:
            cb = QCheckBox(label)
            cb.setChecked(key in visible_keys)
            self._checks[key] = cb
            root.addWidget(cb)

        sort_group = QGroupBox("Sort Priority")
        sort_grid = QGridLayout(sort_group)
        sort_grid.setContentsMargins(12, 16, 12, 12)
        sort_grid.setHorizontalSpacing(8)
        sort_grid.setVerticalSpacing(8)
        sort_grid.addWidget(QLabel("Priority"), 0, 0)
        sort_grid.addWidget(QLabel("Column"), 0, 1)
        sort_grid.addWidget(QLabel("Direction"), 0, 2)

        self._sort_controls: List[tuple[QComboBox, QComboBox]] = []
        column_options = [(self.NONE_SORT_LABEL, self.NONE_SORT_LABEL)] + [
            (label, key) for key, label in columns
        ]
        for row in range(max_sort_levels):
            sort_grid.addWidget(QLabel(f"{row + 1}."), row + 1, 0)

            column_combo = QComboBox()
            for label, key in column_options:
                column_combo.addItem(label, key)

            direction_combo = QComboBox()
            direction_combo.addItem("Ascending", True)
            direction_combo.addItem("Descending", False)

            if row < len(sort_rules):
                rule = sort_rules[row]
                key = str(rule.get("key", self.NONE_SORT_LABEL))
                index = column_combo.findData(key)
                column_combo.setCurrentIndex(index if index >= 0 else 0)
                direction_index = direction_combo.findData(bool(rule.get("ascending", True)))
                direction_combo.setCurrentIndex(direction_index if direction_index >= 0 else 0)
            else:
                direction_combo.setCurrentIndex(0)

            sort_grid.addWidget(column_combo, row + 1, 1)
            sort_grid.addWidget(direction_combo, row + 1, 2)
            self._sort_controls.append((column_combo, direction_combo))

        root.addWidget(sort_group)
        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

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
            rules.append({
                "key": str(key),
                "ascending": bool(direction_combo.currentData()),
            })
        return rules
