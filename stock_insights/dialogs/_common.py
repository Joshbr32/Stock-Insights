"""Shared helpers for the dialogs in this package.

Money formatting, goal/preset spin boxes and the default goal presets.
Layout helpers (panels, forms, button rows) and theme colours live in
stock_insights/widgets.py so the non-dialog windows can use them too.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit, QDoubleSpinBox, QSpinBox

from ..widgets import fmt_money

_DEFAULT_PRESETS = [250_000.0, 500_000.0, 1_000_000.0]
_MAX_MONEY = 1_000_000_000.0
_MAX_SHARES = 1_000_000_000


def _fmt_money(value: float) -> str:
    """$1,234.56 (real minus sign for negatives)."""
    return fmt_money(float(value))


def _fmt_goal(value: float) -> str:
    """$500,000 — goals are whole dollars."""
    return fmt_money(float(value), decimals=0)


def _fmt_preset_label(value: float) -> str:
    """Compact label for a preset button: '250K', '1M', '1.5M', etc."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:g}M"
    if value >= 1_000:
        return f"{value / 1_000:g}K"
    return f"{value:g}"


def _make_goal_spin(value: float = 500_000.0, min_width: int = 130) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(1.0, 999_000_000.0)
    spin.setDecimals(0)
    spin.setSingleStep(10_000.0)
    spin.setPrefix("$")
    spin.setGroupSeparatorShown(True)
    spin.setMinimumWidth(min_width)
    spin.setValue(float(value))
    return spin


def _make_preset_spin(value: float) -> QDoubleSpinBox:
    """Compact spinbox for editing a preset value inside the dialog."""
    return _make_goal_spin(value, min_width=110)


def price_spin(value: float = 0.0, minimum: float = 0.0, blank_at_minimum: bool = False) -> QDoubleSpinBox:
    """Dollar price field: 2 decimals with thousands separators.

    `blank_at_minimum` shows an empty field (not "$0.00") until a price is
    typed, so a missing price is obvious.
    """
    spin = QDoubleSpinBox()
    spin.setRange(minimum, _MAX_MONEY)
    spin.setDecimals(2)
    spin.setPrefix("$")
    spin.setGroupSeparatorShown(True)
    if blank_at_minimum:
        spin.setSpecialValueText(" ")
    spin.setValue(max(minimum, float(value)))
    return spin


def shares_spin(value: int = 1, step: int = 1) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(1, _MAX_SHARES)
    spin.setSingleStep(max(1, int(step)))
    spin.setGroupSeparatorShown(True)
    spin.setValue(max(1, int(value)))
    return spin


def date_edit(value: date | None = None) -> QDateEdit:
    d = value or date.today()
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("MMM d, yyyy")
    edit.setDate(QDate(d.year, d.month, d.day))
    return edit
