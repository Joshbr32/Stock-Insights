"""Goal Dashboard Options dialog + the per-account block widget it uses.

Carved out of portfolio_tab.py during the round-5 split. The dialog
configures shared-vs-individual goal grouping and per-account preset
values.
"""
from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ._common import (
    _DEFAULT_PRESETS,
    GROUP_STYLE,
    _make_goal_spin,
    _make_preset_spin,
)


# ---------------------------------------------------------------------------
# Goal Dashboard Options dialog
# ---------------------------------------------------------------------------

class _AccountGoalBlock(QGroupBox):
    """A self-contained block for one account inside the GoalDashboardOptionsDialog.

    Layout
    ──────
      ┌ Josh ──────────────────────────────────────────────────────────────┐
      │  [x] Include in shared goal group                                  │
      │  Individual Goal: [$ 500,000]   (hidden when shared)              │
      │  Presets:  [$ 250,000]  [$ 500,000]  [$ 1,000,000]               │
      └────────────────────────────────────────────────────────────────────┘
    """

    sharedToggled = Signal()

    def __init__(
            self,
            account_name: str,
            is_shared: bool,
            current_goal: float,
            preset_values: List[float],
            parent=None,
    ):
        super().__init__(account_name, parent)
        self.setStyleSheet(GROUP_STYLE)
        self._account_name = account_name

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 16, 14, 10)
        root.setSpacing(6)

        # -- Shared checkbox --
        self.cb_shared = QCheckBox("Include in shared goal group")
        self.cb_shared.setChecked(is_shared)
        root.addWidget(self.cb_shared)

        # -- Individual goal row (visible when NOT shared) --
        self._indiv_row = QWidget()
        indiv_h = QHBoxLayout(self._indiv_row)
        indiv_h.setContentsMargins(0, 0, 0, 0)
        indiv_h.setSpacing(8)
        indiv_h.addWidget(QLabel("Individual Goal:"))
        self.goal_spin = _make_goal_spin(current_goal)
        indiv_h.addWidget(self.goal_spin)
        indiv_h.addStretch(1)
        root.addWidget(self._indiv_row)

        # -- Presets row (always visible) --
        presets_h = QHBoxLayout()
        presets_h.setContentsMargins(0, 0, 0, 0)
        presets_h.setSpacing(8)
        presets_h.addWidget(QLabel("Presets:"))
        p = preset_values if len(preset_values) == 3 else list(_DEFAULT_PRESETS)
        self.preset_spins: List[QDoubleSpinBox] = []
        for i, val in enumerate(p):
            lbl = QLabel(f"{'Min' if i == 0 else 'Mid' if i == 1 else 'Max'}:")
            spin = _make_preset_spin(val)
            self.preset_spins.append(spin)
            presets_h.addWidget(lbl)
            presets_h.addWidget(spin)
        presets_h.addStretch(1)
        root.addLayout(presets_h)

        self._sync_visibility()
        self.cb_shared.stateChanged.connect(self._on_toggle)

    def _on_toggle(self):
        self._sync_visibility()
        self.sharedToggled.emit()

    def _sync_visibility(self):
        self._indiv_row.setVisible(not self.cb_shared.isChecked())

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
    """Goal Dashboard Options dialog — account grouping, targets, and per-account presets.

    ┌───────────────────────────────────────────────────────────────────┐
    │  [info]                                                           │
    │                                                                   │
    │  Shared Goal:  [$ 500,000 ▲▼]                                    │
    │  (hidden / greyed when no accounts are checked)                   │
    │                                                                   │
    │  ┌ Josh ──────────────────────────────────────────────────────┐  │
    │  │  [x] Include in shared goal group                          │  │
    │  │  Presets:  Min [$ 250K]  Mid [$ 500K]  Max [$ 1M]         │  │
    │  └────────────────────────────────────────────────────────────┘  │
    │                                                                   │
    │  ┌ Narmeen ────────────────────────────────────────────────────┐  │
    │  │  [ ] Include in shared goal group                           │  │
    │  │  Individual Goal:  [$ 25,000]                              │  │
    │  │  Presets:  Min [$ 10K]  Mid [$ 25K]  Max [$ 50K]          │  │
    │  └────────────────────────────────────────────────────────────┘  │
    │                                                                   │
    │                               [Cancel]  [Save]                   │
    └───────────────────────────────────────────────────────────────────┘
    """

    def __init__(
            self,
            accounts: List[str],
            included_accounts: List[str],
            goal_targets: Dict[str, float],
            preset_values: Dict[str, List[float]],
            parent=None,
    ):
        super().__init__(parent)
        self._accounts = accounts
        self.setWindowTitle("Goal Dashboard Options")
        self.setMinimumWidth(560)
        self.resize(600, min(100 + 130 * len(accounts) + 80, 680))

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # -- Info --
        info = QLabel(
            "Check accounts to merge their trades toward a <b>shared goal</b>. "
            "Unchecked accounts each track their own goal independently. "
            "Each account's <b>presets</b> appear as quick-set buttons on their Goal Dashboard."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        # -- Shared goal row (visible only when at least one account is checked) --
        self._shared_row = QWidget()
        shared_h = QHBoxLayout(self._shared_row)
        shared_h.setContentsMargins(0, 4, 0, 4)
        shared_h.setSpacing(8)
        shared_h.addWidget(QLabel("<b>Shared Group Goal:</b>"))
        default_shared = goal_targets.get(
            included_accounts[0] if included_accounts else (accounts[0] if accounts else ""),
            500_000.0,
        )
        self.shared_goal_spin = _make_goal_spin(default_shared)
        shared_h.addWidget(self.shared_goal_spin)
        shared_h.addStretch(1)
        root.addWidget(self._shared_row)

        # -- Account blocks in a scroll area --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        container = QWidget()
        blocks_vbox = QVBoxLayout(container)
        blocks_vbox.setContentsMargins(4, 4, 4, 4)
        blocks_vbox.setSpacing(8)

        included_set = set(included_accounts)
        self._blocks: List[_AccountGoalBlock] = []
        for account in accounts:
            block = _AccountGoalBlock(
                account_name=account,
                is_shared=account in included_set,
                current_goal=goal_targets.get(account, 500_000.0),
                preset_values=preset_values.get(account, list(_DEFAULT_PRESETS)),
                parent=container,
            )
            block.sharedToggled.connect(self._update_shared_row_visibility)
            blocks_vbox.addWidget(block)
            self._blocks.append(block)

        blocks_vbox.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # -- Buttons --
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._update_shared_row_visibility()

    def _update_shared_row_visibility(self):
        has_shared = any(b.is_shared for b in self._blocks)
        self._shared_row.setVisible(has_shared)

    # ---- result accessors ----

    def selected_accounts(self) -> List[str]:
        return [b.account_name for b in self._blocks if b.is_shared]

    def shared_goal(self) -> float:
        return float(self.shared_goal_spin.value())

    def individual_goals(self) -> Dict[str, float]:
        return {b.account_name: b.individual_goal for b in self._blocks if not b.is_shared}

    def all_preset_values(self) -> Dict[str, List[float]]:
        return {b.account_name: b.preset_values for b in self._blocks}
