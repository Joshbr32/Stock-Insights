from __future__ import annotations

from PySide6.QtCore import Qt
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
    """Simple collapsible container used by the settings dialog."""

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

    def _toggle(self, checked: bool) -> None:
        self.btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.content.setVisible(checked)

    def setContentLayout(self, layout) -> None:
        QWidget().setLayout(self._content_layout)
        self._content_layout = layout
        self.content.setLayout(layout)


class SettingsDialog(QDialog):
    """Application settings dialog.

    Current groups:
    - Data Refresh: timer intervals and auto refresh toggles
    - Appearance: theme override
    """

    def __init__(self, parent=None, settings=None, current_values=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(460, 320)

        self.settings = settings
        cv = current_values or {}

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Data refresh settings
        grp_refresh = CollapsibleGroup("Data Refresh", collapsed=False)
        refresh_form = QFormLayout()
        refresh_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.sb_l1 = QSpinBox()
        self.sb_l1.setRange(5, 600)
        self.sb_l1.setSuffix(" s")
        self.sb_l1.setValue(int(cv.get("L1_INTERVAL", 20_000) / 1000))

        self.sb_l2 = QSpinBox()
        self.sb_l2.setRange(1, 120)
        self.sb_l2.setSuffix(" min")
        self.sb_l2.setValue(int(cv.get("L2_INTERVAL", 300_000) / 60_000))

        self.sb_net = QSpinBox()
        self.sb_net.setRange(5, 600)
        self.sb_net.setSuffix(" s")
        self.sb_net.setValue(int(cv.get("NET_INTERVAL", 10_000) / 1000))

        self.cb_l1 = QCheckBox("Enable Level 1 auto refresh")
        self.cb_l2 = QCheckBox("Enable Level 2 auto refresh")
        self.cb_l1.setChecked(bool(cv.get("L1_ENABLED", True)))
        self.cb_l2.setChecked(bool(cv.get("L2_ENABLED", True)))

        refresh_form.addRow(QLabel("Level 1 refresh:"), self.sb_l1)
        refresh_form.addRow(QLabel("Level 2 refresh:"), self.sb_l2)
        refresh_form.addRow(QLabel("Connectivity check:"), self.sb_net)
        refresh_form.addRow(self.cb_l1)
        refresh_form.addRow(self.cb_l2)
        grp_refresh.setContentLayout(refresh_form)
        root.addWidget(grp_refresh)

        # Appearance settings
        grp_appearance = CollapsibleGroup("Appearance", collapsed=False)
        app_form = QFormLayout()
        app_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(["System", "Light", "Dark"])
        self.cmb_theme.setCurrentText(cv.get("THEME_OVERRIDE", "System"))
        app_form.addRow(QLabel("Theme:"), self.cmb_theme)
        grp_appearance.setContentLayout(app_form)
        root.addWidget(grp_appearance)

        # Dialog buttons
        btns = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        root.addLayout(btns)

    def get_values(self):
        return {
            "L1_INTERVAL": self.sb_l1.value() * 1000,
            "L2_INTERVAL": self.sb_l2.value() * 60 * 1000,
            "NET_INTERVAL": self.sb_net.value() * 1000,
            "L1_ENABLED": self.cb_l1.isChecked(),
            "L2_ENABLED": self.cb_l2.isChecked(),
            "THEME_OVERRIDE": self.cmb_theme.currentText(),
        }
