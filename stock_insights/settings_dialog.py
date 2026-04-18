"""Application settings dialog. Uses the same QGroupBox-based aesthetic
as MarkDownDialog / DoubleDownDialog / TradeEditDialog so the modal
UI feels consistent throughout the app."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
)

from .theme import FONT_SIZE_LABELS, THEME_NAMES

# Keep in sync with the GROUP_STYLE used in portfolio_tab.py so every
# dialog's grouped sections look identical.
GROUP_STYLE = (
    "QGroupBox { margin-top: 8px; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 2px 8px; }"
)


class SettingsDialog(QDialog):
    """Application settings — Data Refresh, Trade Defaults, Appearance.

    Goal targets live in View > Goal Dashboard Options.
    """

    def __init__(self, parent=None, settings=None, current_values=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(440)

        self.settings = settings
        cv = current_values or {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Section: Data Refresh ───────────────────────────────────────
        refresh_grp = QGroupBox("Data Refresh")
        refresh_grp.setStyleSheet(GROUP_STYLE)
        refresh_form = QFormLayout(refresh_grp)
        refresh_form.setContentsMargins(14, 14, 14, 14)
        refresh_form.setSpacing(10)
        refresh_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        refresh_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.sb_l1 = QSpinBox()
        self.sb_l1.setRange(5, 600)
        self.sb_l1.setSuffix(" s")
        self.sb_l1.setValue(int(cv.get("L1_INTERVAL", 20000) / 1000))

        self.sb_net = QSpinBox()
        self.sb_net.setRange(5, 600)
        self.sb_net.setSuffix(" s")
        self.sb_net.setValue(int(cv.get("NET_INTERVAL", 10000) / 1000))

        self.cb_l1 = QCheckBox("Enable marks auto-refresh")
        self.cb_l1.setChecked(bool(cv.get("L1_ENABLED", True)))

        refresh_form.addRow("Marks refresh interval", self.sb_l1)
        refresh_form.addRow("Connectivity check", self.sb_net)
        refresh_form.addRow("", self.cb_l1)
        root.addWidget(refresh_grp)

        # ── Section: Trade Defaults ─────────────────────────────────────
        trade_grp = QGroupBox("Trade Defaults")
        trade_grp.setStyleSheet(GROUP_STYLE)
        trade_form = QFormLayout(trade_grp)
        trade_form.setContentsMargins(14, 14, 14, 14)
        trade_form.setSpacing(10)
        trade_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        trade_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.trade_default_quantity = QSpinBox()
        self.trade_default_quantity.setRange(1, 1_000_000_000)
        self.trade_default_quantity.setValue(int(cv.get("TRADE_DEFAULT_QUANTITY", 1)))

        self.trade_quantity_increment = QSpinBox()
        self.trade_quantity_increment.setRange(1, 1_000_000_000)
        self.trade_quantity_increment.setValue(int(cv.get("TRADE_QUANTITY_INCREMENT", 1)))

        trade_form.addRow("Default quantity", self.trade_default_quantity)
        trade_form.addRow("Quantity increment", self.trade_quantity_increment)
        root.addWidget(trade_grp)

        # ── Section: Appearance ─────────────────────────────────────────
        appearance_grp = QGroupBox("Appearance")
        appearance_grp.setStyleSheet(GROUP_STYLE)
        app_form = QFormLayout(appearance_grp)
        app_form.setContentsMargins(14, 14, 14, 14)
        app_form.setSpacing(10)
        app_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        app_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.cmb_colour_mode = QComboBox()
        self.cmb_colour_mode.addItems(["System", "Light", "Dark"])
        self.cmb_colour_mode.setCurrentText(cv.get("THEME_OVERRIDE", "System"))

        self.cmb_theme_name = QComboBox()
        self.cmb_theme_name.addItems(THEME_NAMES)
        self.cmb_theme_name.setCurrentText(cv.get("THEME_NAME", "Default"))

        self.cb_match_system_accent = QCheckBox("Match System Accent Colour")
        self.cb_match_system_accent.setChecked(bool(cv.get("MATCH_SYSTEM_ACCENT", True)))

        self.cmb_font_size = QComboBox()
        self.cmb_font_size.addItems(FONT_SIZE_LABELS)
        self.cmb_font_size.setCurrentText(cv.get("FONT_SIZE", "Normal"))

        app_form.addRow("Colour Mode", self.cmb_colour_mode)
        app_form.addRow("Theme", self.cmb_theme_name)
        app_form.addRow("Font Size", self.cmb_font_size)
        app_form.addRow("", self.cb_match_system_accent)
        root.addWidget(appearance_grp)

        root.addStretch(1)

        # ── Standard button row (matches other dialogs' rhythm) ────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_values(self) -> dict:
        return {
            "L1_INTERVAL": self.sb_l1.value() * 1000,
            "NET_INTERVAL": self.sb_net.value() * 1000,
            "L1_ENABLED": self.cb_l1.isChecked(),
            "TRADE_DEFAULT_QUANTITY": int(self.trade_default_quantity.value()),
            "TRADE_QUANTITY_INCREMENT": int(self.trade_quantity_increment.value()),
            "THEME_OVERRIDE": self.cmb_colour_mode.currentText(),
            "THEME_NAME": self.cmb_theme_name.currentText(),
            "FONT_SIZE": self.cmb_font_size.currentText(),
            "MATCH_SYSTEM_ACCENT": self.cb_match_system_accent.isChecked(),
        }
