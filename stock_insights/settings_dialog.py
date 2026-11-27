"""File > Settings: price refresh, connection check, new-trade defaults, appearance.

Pure form: MainWindow passes the current values in `current_values` and
reads the result back with `get_values()` (same keys, intervals in ms).
Goal targets live in View > Goal options, not here.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QSpinBox,
)

from .theme import FONT_SIZE_LABELS, THEME_NAMES
from .widgets import Panel, add_dialog_buttons, align_form_labels, dialog_layout

# Mode combo: shown label -> value stored under ui/THEME_OVERRIDE.
_MODES = [("Match Windows", "System"), ("Light", "Light"), ("Dark", "Dark")]
_INTERVAL_RANGE_S = (5, 600)
_QTY_MAX = 1_000_000_000


def _seconds_spin(value_ms) -> QSpinBox:
    sb = QSpinBox()
    sb.setRange(*_INTERVAL_RANGE_S)
    sb.setSuffix(" seconds")
    sb.setValue(int(int(value_ms) / 1000))
    return sb


class SettingsDialog(QDialog):
    """Application settings. `settings` is kept for API compatibility."""

    def __init__(self, parent=None, settings=None, current_values=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(460)

        self.settings = settings
        cv = current_values or {}
        root = dialog_layout(self)

        # ── Prices ──────────────────────────────────────────────────────
        prices = Panel("Prices")
        form = prices.form()
        self.cb_l1 = QCheckBox("Refresh prices automatically")
        self.cb_l1.setChecked(bool(cv.get("L1_ENABLED", True)))
        self.sb_l1 = _seconds_spin(cv.get("L1_INTERVAL", 20_000))
        form.addRow(self.cb_l1)
        form.addRow("Refresh every", self.sb_l1)
        self.cb_l1.toggled.connect(self.sb_l1.setEnabled)
        self.sb_l1.setEnabled(self.cb_l1.isChecked())
        root.addWidget(prices)

        # ── Connection ──────────────────────────────────────────────────
        conn = Panel("Connection")
        self.sb_net = _seconds_spin(cv.get("NET_INTERVAL", 10_000))
        conn.form().addRow("Check connection every", self.sb_net)
        root.addWidget(conn)

        # ── New trades ──────────────────────────────────────────────────
        trades = Panel("New trades", subtitle="Starting values when you log a trade.")
        tform = trades.form()
        self.trade_default_quantity = QSpinBox()
        self.trade_default_quantity.setRange(1, _QTY_MAX)
        self.trade_default_quantity.setGroupSeparatorShown(True)
        self.trade_default_quantity.setValue(int(cv.get("TRADE_DEFAULT_QUANTITY", 1)))
        self.trade_quantity_increment = QSpinBox()
        self.trade_quantity_increment.setRange(1, _QTY_MAX)
        self.trade_quantity_increment.setGroupSeparatorShown(True)
        self.trade_quantity_increment.setValue(int(cv.get("TRADE_QUANTITY_INCREMENT", 1)))
        tform.addRow("Shares", self.trade_default_quantity)
        tform.addRow("Arrow keys step by", self.trade_quantity_increment)
        root.addWidget(trades)

        # ── Appearance ──────────────────────────────────────────────────
        look = Panel("Appearance")
        aform = look.form()
        self.cmb_theme_name = QComboBox()
        self.cmb_theme_name.addItems(THEME_NAMES)
        self.cmb_theme_name.setCurrentText(cv.get("THEME_NAME", "Default"))
        self.cmb_colour_mode = QComboBox()
        for label, value in _MODES:
            self.cmb_colour_mode.addItem(label, value)
        idx = self.cmb_colour_mode.findData(cv.get("THEME_OVERRIDE", "System"))
        self.cmb_colour_mode.setCurrentIndex(max(0, idx))
        self.cmb_font_size = QComboBox()
        self.cmb_font_size.addItems(FONT_SIZE_LABELS)
        self.cmb_font_size.setCurrentText(cv.get("FONT_SIZE", "Normal"))
        # No theme uses the Windows accent any more (theme.py), so the option
        # is not shown; the value round-trips so the saved setting survives.
        self.cb_match_system_accent = QCheckBox("Use the Windows accent colour", self)
        self.cb_match_system_accent.setChecked(bool(cv.get("MATCH_SYSTEM_ACCENT", True)))
        self.cb_match_system_accent.setVisible(False)
        aform.addRow("Theme", self.cmb_theme_name)
        aform.addRow("Mode", self.cmb_colour_mode)
        aform.addRow("Text size", self.cmb_font_size)
        root.addWidget(look)
        align_form_labels(form, conn.form(), tform, aform)

        root.addStretch(1)
        add_dialog_buttons(self, root, "Save")

    def get_values(self) -> dict:
        return {
            "L1_INTERVAL": self.sb_l1.value() * 1000,
            "NET_INTERVAL": self.sb_net.value() * 1000,
            "L1_ENABLED": self.cb_l1.isChecked(),
            "TRADE_DEFAULT_QUANTITY": int(self.trade_default_quantity.value()),
            "TRADE_QUANTITY_INCREMENT": int(self.trade_quantity_increment.value()),
            "THEME_OVERRIDE": self.cmb_colour_mode.currentData() or "System",
            "THEME_NAME": self.cmb_theme_name.currentText(),
            "FONT_SIZE": self.cmb_font_size.currentText(),
            "MATCH_SYSTEM_ACCENT": self.cb_match_system_accent.isChecked(),
        }
