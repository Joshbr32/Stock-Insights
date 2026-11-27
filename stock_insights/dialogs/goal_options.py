"""View > Goal options: shared vs. per-portfolio goals and quick-set amounts.

Layout: an intro line, the shared goal (shown only while at least one
portfolio counts toward it), then one panel per portfolio with a
"Count toward the shared goal" checkbox, its own goal (hidden while
shared) and three quick-set amounts (the preset buttons on its dashboard).
Results are read back with selected_accounts() / shared_goal() /
individual_goals() / all_preset_values().
"""
from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ._common import _DEFAULT_PRESETS, _make_goal_spin, _make_preset_spin
from ..widgets import GAP, Panel, add_dialog_buttons, dialog_layout, muted_label

_PRESET_NAMES = ("Low", "Middle", "High")


class _AccountGoalBlock(Panel):
    """One portfolio's goal settings inside GoalDashboardOptionsDialog."""

    sharedToggled = Signal()

    def __init__(self, account_name: str, is_shared: bool, current_goal: float,
                 preset_values: List[float], parent=None):
        super().__init__(account_name, parent)
        self._account_name = account_name

        self.cb_shared = QCheckBox("Count toward the shared goal")
        self.cb_shared.setChecked(is_shared)
        self.body.addWidget(self.cb_shared)

        form = self.form()
        self.goal_spin = _make_goal_spin(current_goal)
        self._indiv_label = QLabel("Own goal")
        form.addRow(self._indiv_label, self.goal_spin)

        presets_row = QWidget()
        h = QHBoxLayout(presets_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        values = preset_values if len(preset_values) == 3 else list(_DEFAULT_PRESETS)
        self.preset_spins: List[QDoubleSpinBox] = []
        for name, val in zip(_PRESET_NAMES, values):
            spin = _make_preset_spin(val)
            spin.setToolTip(f"{name} quick-set amount")
            spin.setAccessibleName(f"{account_name} {name.lower()} quick-set amount")
            self.preset_spins.append(spin)
            h.addWidget(spin, 1)
        form.addRow("Quick-set amounts", presets_row)

        self._sync_visibility()
        self.cb_shared.toggled.connect(self._on_toggle)

    def _on_toggle(self, *_args):
        self._sync_visibility()
        self.sharedToggled.emit()

    def _sync_visibility(self):
        own = not self.cb_shared.isChecked()
        self.goal_spin.setVisible(own)
        self._indiv_label.setVisible(own)

    # ---- accessors ----

    @property
    def account_name(self) -> str:
        return self._account_name

    @property
    def is_shared(self) -> bool:
        return self.cb_shared.isChecked()

    @property
    def individual_goal(self) -> float:
        return float(self.goal_spin.value())

    @property
    def preset_values(self) -> List[float]:
        return [float(s.value()) for s in self.preset_spins]


class GoalDashboardOptionsDialog(QDialog):
    """Goal options: shared-goal membership, targets, per-portfolio presets."""

    def __init__(self, accounts: List[str], included_accounts: List[str], goal_targets: Dict[str, float],
                 preset_values: Dict[str, List[float]], parent=None):
        super().__init__(parent)
        self._accounts = accounts
        self.setWindowTitle("Goal options")
        self.setMinimumWidth(560)
        self.resize(600, min(170 + 190 * len(accounts), 720))

        root = dialog_layout(self)
        root.addWidget(muted_label(
            "Portfolios that count toward the shared goal pool their profit into one target. "
            "The others each track their own goal. Quick-set amounts appear as buttons on "
            "each portfolio's goal dashboard."))

        self._shared_row = Panel()
        default_shared = goal_targets.get(
            included_accounts[0] if included_accounts else (accounts[0] if accounts else ""), 500_000.0)
        self.shared_goal_spin = _make_goal_spin(default_shared)
        self._shared_row.form().addRow("Shared goal", self.shared_goal_spin)
        root.addWidget(self._shared_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        blocks = QVBoxLayout(container)
        blocks.setContentsMargins(0, 0, 0, 0)
        blocks.setSpacing(GAP)

        included = set(included_accounts)
        self._blocks: List[_AccountGoalBlock] = []
        for account in accounts:
            block = _AccountGoalBlock(
                account_name=account,
                is_shared=account in included,
                current_goal=goal_targets.get(account, 500_000.0),
                preset_values=preset_values.get(account, list(_DEFAULT_PRESETS)),
                parent=container,
            )
            block.sharedToggled.connect(self._update_shared_row_visibility)
            blocks.addWidget(block)
            self._blocks.append(block)
        blocks.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        add_dialog_buttons(self, root, "Save")
        self._update_shared_row_visibility()

    def _update_shared_row_visibility(self):
        self._shared_row.setVisible(any(b.is_shared for b in self._blocks))

    # ---- result accessors ----

    def selected_accounts(self) -> List[str]:
        return [b.account_name for b in self._blocks if b.is_shared]

    def shared_goal(self) -> float:
        return float(self.shared_goal_spin.value())

    def individual_goals(self) -> Dict[str, float]:
        return {b.account_name: b.individual_goal for b in self._blocks if not b.is_shared}

    def all_preset_values(self) -> Dict[str, List[float]]:
        return {b.account_name: b.preset_values for b in self._blocks}
