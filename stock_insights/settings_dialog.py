from PySide6.QtCore import Qt
from .theme import FONT_SIZE_LABELS, THEME_NAMES
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleGroup(QWidget):
    def __init__(self, title: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        self.btn = QToolButton(self)
        self.btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn.setArrowType(Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow)
        self.btn.setText(title)
        self.btn.setCheckable(True)
        self.btn.setChecked(not collapsed)
        self.btn.clicked.connect(self._toggle)

        header.addWidget(self.btn)
        header.addStretch(1)

        self.content = QFrame(self)
        self.content.setFrameShape(QFrame.Shape.NoFrame)
        self.content.setVisible(not collapsed)
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(12, 6, 0, 6)
        self._content_layout.setSpacing(8)

        root.addLayout(header)
        root.addWidget(self.content)

    def _toggle(self, checked: bool):
        self.btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.content.setVisible(checked)

    def setContentLayout(self, layout):
        QWidget().setLayout(self._content_layout)
        self._content_layout = layout
        self.content.setLayout(layout)


class SettingsDialog(QDialog):
    """Application settings — Data Refresh, Trade Defaults, Appearance.

    Goal targets have been moved to View > Goal Dashboard Accounts.
    """

    def __init__(self, parent=None, settings=None, current_values=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(480, 320)

        self.settings = settings
        cv = current_values or {}

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- Data Refresh ----
        grp_refresh = CollapsibleGroup("Data Refresh", collapsed=False)
        refresh_form = QFormLayout()
        refresh_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

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

        refresh_form.addRow(QLabel("Marks refresh interval:"), self.sb_l1)
        refresh_form.addRow(QLabel("Connectivity check:"), self.sb_net)
        refresh_form.addRow(self.cb_l1)
        grp_refresh.setContentLayout(refresh_form)
        root.addWidget(grp_refresh)

        # ---- Trade Defaults ----
        grp_trade = CollapsibleGroup("Trade Defaults", collapsed=False)
        trade_form = QFormLayout()
        trade_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.trade_default_quantity = QSpinBox()
        self.trade_default_quantity.setRange(1, 1_000_000_000)
        self.trade_default_quantity.setValue(int(cv.get("TRADE_DEFAULT_QUANTITY", 1)))

        self.trade_quantity_increment = QSpinBox()
        self.trade_quantity_increment.setRange(1, 1_000_000_000)
        self.trade_quantity_increment.setValue(int(cv.get("TRADE_QUANTITY_INCREMENT", 1)))

        trade_form.addRow(QLabel("Default Quantity:"), self.trade_default_quantity)
        trade_form.addRow(QLabel("Quantity Increment:"), self.trade_quantity_increment)
        grp_trade.setContentLayout(trade_form)
        root.addWidget(grp_trade)

        # ---- Appearance ----
        grp_appearance = CollapsibleGroup("Appearance", collapsed=False)
        app_form = QFormLayout()
        app_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

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

        app_form.addRow(QLabel("Colour Mode:"), self.cmb_colour_mode)
        app_form.addRow(QLabel("Theme:"), self.cmb_theme_name)
        app_form.addRow(QLabel("Font Size:"), self.cmb_font_size)
        app_form.addRow(self.cb_match_system_accent)
        grp_appearance.setContentLayout(app_form)
        root.addWidget(grp_appearance)

        root.addStretch(1)

        btns = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        root.addLayout(btns)

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
