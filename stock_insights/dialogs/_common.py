"""Shared helpers for the dialogs in this package.

Lifted from portfolio_tab.py during the round-5 split. Everything here
is style/format/preset infrastructure that multiple dialogs need —
keeping it in one place avoids each new dialog redefining its own
spinbox factory or money formatter.
"""
from __future__ import annotations

import json
from typing import List

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDoubleSpinBox

GROUP_STYLE = (
    "QGroupBox { margin-top: 8px; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 2px 8px; }"
)

_DEFAULT_PRESETS = [250_000.0, 500_000.0, 1_000_000.0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_money(value: float) -> str:
    return f"$ {float(value):,.2f}"


def _fmt_goal(value: float) -> str:
    return f"$ {float(value):,.0f}"


def _fmt_preset_label(value: float) -> str:
    """Compact label for a preset button: '250K', '1M', '1.5M', etc."""
    if value >= 1_000_000:
        n = value / 1_000_000
        return f"{n:g}M"
    if value >= 1_000:
        n = value / 1_000
        return f"{n:g}K"
    return f"{value:g}"


def _make_goal_spin(value: float = 500_000.0) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(1.0, 999_000_000.0)
    spin.setDecimals(0)
    spin.setSingleStep(10_000.0)
    spin.setPrefix("$ ")
    spin.setMinimumWidth(130)
    spin.setValue(float(value))
    return spin


def _make_preset_spin(value: float) -> QDoubleSpinBox:
    """Compact spinbox for editing a preset value inside the dialog."""
    spin = QDoubleSpinBox()
    spin.setRange(1.0, 999_000_000.0)
    spin.setDecimals(0)
    spin.setSingleStep(10_000.0)
    spin.setPrefix("$ ")
    spin.setMinimumWidth(110)
    spin.setValue(float(value))
    return spin


def _load_account_presets(settings: QSettings, account_name: str) -> List[float]:
    """Load the 3 preset values for an account, falling back to defaults."""
    raw = settings.value(f"goals/presets/{account_name}", None)
    if raw is not None:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list) and len(parsed) == 3:
                return [max(1.0, float(x)) for x in parsed]
        except Exception:
            pass
    return list(_DEFAULT_PRESETS)


def _save_account_presets(settings: QSettings, account_name: str, presets: List[float]):
    settings.setValue(f"goals/presets/{account_name}", json.dumps([float(p) for p in presets]))
