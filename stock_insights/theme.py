import ctypes
import sys
from typing import Optional, Tuple
from PySide6.QtCore import QTimer, QObject
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

if sys.platform.startswith("win"):
    import winreg


def _windows_high_contrast_enabled() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        SPI_GETHIGHCONTRAST = 0x0042

        class HIGHCONTRAST(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint), ("lpszDefaultScheme", ctypes.c_wchar_p)]

        hc = HIGHCONTRAST()
        hc.cbSize = ctypes.sizeof(HIGHCONTRAST)
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0)
        HCF_HIGHCONTRASTON = 0x00000001
        return bool(hc.dwFlags & HCF_HIGHCONTRASTON)
    except Exception:
        return False


class ThemeManager(QObject):
    override_mode: str = "System"
    match_system_accent: bool = True

    def __init__(self, window, poll_secs: int = 3):
        super().__init__(window)
        self.win = window
        self.poll_secs = poll_secs
        self._last_state = None
        self._timer: Optional[QTimer] = None
        self._fixed_light_accent = (10, 102, 194)
        self._fixed_dark_accent = (96, 165, 250)

    def _windows_is_light(self) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as k:
                v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
                return bool(v)
        except Exception:
            return False

    def _windows_accent_rgb(self) -> Tuple[int, int, int]:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent",
            ) as k:
                v, _ = winreg.QueryValueEx(k, "AccentColor")
                r = v & 0xFF
                g = (v >> 8) & 0xFF
                b = (v >> 16) & 0xFF
                return (r, g, b)
        except Exception:
            pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
                v, _ = winreg.QueryValueEx(k, "ColorizationColor")
                r = (v >> 16) & 0xFF
                g = (v >> 8) & 0xFF
                b = v & 0xFF
                return (r, g, b)
        except Exception:
            pass
        try:
            color = ctypes.c_uint()
            opaque_blend = ctypes.c_int()
            if ctypes.windll.dwmapi.DwmGetColorizationColor(ctypes.byref(color), ctypes.byref(opaque_blend)) == 0:
                v = color.value
                r = (v >> 16) & 0xFF
                g = (v >> 8) & 0xFF
                b = v & 0xFF
                return (r, g, b)
        except Exception:
            pass
        return self._fixed_light_accent

    def _accent_for_mode(self, is_light: bool) -> Tuple[int, int, int]:
        if self.match_system_accent and sys.platform.startswith("win"):
            return self._windows_accent_rgb()
        return self._fixed_light_accent if is_light else self._fixed_dark_accent

    def current_state(self) -> tuple:
        if self.override_mode in ("Light", "Dark"):
            is_light = self.override_mode == "Light"
        elif sys.platform.startswith("win"):
            is_light = self._windows_is_light()
        else:
            is_light = False

        r, g, b = self._accent_for_mode(is_light)
        return (is_light, r, g, b, self.match_system_accent)

    def set_override_mode(self, mode: str):
        self.override_mode = mode if mode in ("System", "Light", "Dark") else "System"
        self.apply()

    def set_match_system_accent(self, enabled: bool):
        self.match_system_accent = bool(enabled)
        self.apply()

    def start_watching(self):
        if self._timer is None:
            self._timer = QTimer(self.win)
            self._timer.setInterval(self.poll_secs * 1000)
            self._timer.timeout.connect(self._maybe_update_theme)
            self._timer.start()

    def _maybe_update_theme(self):
        state = self.current_state()
        if state != self._last_state:
            self.apply()

    def apply(self):
        if sys.platform.startswith("win") and _windows_high_contrast_enabled():
            self.win.setStyleSheet("")
            return
        is_light, r, g, b, match_system_accent = self.current_state()
        self._last_state = (is_light, r, g, b, match_system_accent)
        accent = QColor(r, g, b)

        if is_light:
            palette = self._light_palette(accent)
            stylesheet = self._light_stylesheet(accent)
        else:
            palette = self._dark_palette(accent)
            stylesheet = self._dark_stylesheet(accent)

        app = QApplication.instance()
        if app is not None:
            app.setPalette(palette)
            app.setStyleSheet(stylesheet)

        self.win.setPalette(palette)
        self.win.setStyleSheet(stylesheet)

        try:
            self.win.style().unpolish(self.win)
            self.win.style().polish(self.win)
        except Exception:
            pass
        self.win.update()

    def _dark_palette(self, accent: QColor) -> QPalette:
        p = QPalette()
        p.setColor(QPalette.Window, QColor("#0f1115"))
        p.setColor(QPalette.Base, QColor("#14171d"))
        p.setColor(QPalette.AlternateBase, QColor("#171a21"))
        p.setColor(QPalette.ToolTipBase, QColor("#10131a"))
        p.setColor(QPalette.ToolTipText, QColor("#eaeef2"))
        p.setColor(QPalette.Text, QColor("#eaeef2"))
        p.setColor(QPalette.Button, QColor("#1f2430"))
        p.setColor(QPalette.ButtonText, QColor("#eaeef2"))
        p.setColor(QPalette.Highlight, accent)
        p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        p.setColor(QPalette.WindowText, QColor("#eaeef2"))
        p.setColor(QPalette.PlaceholderText, QColor("#a9b1bd"))
        return p

    def _light_palette(self, accent: QColor) -> QPalette:
        p = QPalette()
        p.setColor(QPalette.Window, QColor("#ffffff"))
        p.setColor(QPalette.Base, QColor("#f8fafc"))
        p.setColor(QPalette.AlternateBase, QColor("#eef2f7"))
        p.setColor(QPalette.ToolTipBase, QColor("#f3f5f7"))
        p.setColor(QPalette.ToolTipText, QColor("#0f1115"))
        p.setColor(QPalette.Text, QColor("#0f1115"))
        p.setColor(QPalette.Button, QColor("#ffffff"))
        p.setColor(QPalette.ButtonText, QColor("#0f1115"))
        p.setColor(QPalette.Highlight, accent)
        p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        p.setColor(QPalette.WindowText, QColor("#0f1115"))
        p.setColor(QPalette.PlaceholderText, QColor("#4b5563"))
        return p

    def _dark_stylesheet(self, accent: QColor) -> str:
        acc = accent.name()
        return f"""
        QMainWindow {{ background: #0f1115; color: #eaeef2; }}
        #leftPane {{ background: #10131a; border-right: 1px solid #232833; }}
        #leftTitle {{ color: #a9b1bd; font-size: 14px; font-weight: 700; padding: 8px 4px; }}
        QToolTip {{ color: #eaeef2; background: #10131a; border: 1px solid #232833; }}
        QLineEdit {{ background: #171a21; border: 1px solid #232833; border-radius: 8px; padding: 6px 10px; color: #eaeef2; }}
        QLineEdit:focus {{ border: 1px solid {acc}; box-shadow: 0 0 0 2px {acc}33; }}
        QPushButton {{ background: #1f2430; border: 1px solid #2b3240; color: #eaeef2; border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
        QPushButton:hover {{ background: #262d3a; }}
        QPushButton:pressed {{ background: #2b3240; }}
        QPushButton:focus {{ outline: none; border: 1px solid {acc}; }}
        QTabBar::tab {{ background: #171a21; color: #eaeef2; padding: 8px 14px; border: 1px solid #232833; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 6px; }}
        QTabBar::tab:selected {{ background: #1f2430; border-color: {acc}; }}
        QTabWidget::pane {{ border: 1px solid #232833; top: -0.2em; }}
        QGroupBox {{ border: 1px solid #232833; border-radius: 10px; margin-top: 16px; }}
        QGroupBox::title {{ left: 12px; padding: 0 4px; color: #a9b1bd; }}
        QTableWidget {{ background: #0f1115; gridline-color: #232833; color: #eaeef2; alternate-background-color: #14171d; border: 1px solid #232833; border-radius: 8px; }}
        QHeaderView::section {{ background: #171a21; color: #eaeef2; border: 0px; padding: 6px; }}
        QTableWidget::item:selected {{ background: {acc}; color: white; }}
        QComboBox {{ background: #171a21; color: #eaeef2; border: 1px solid #232833; border-radius: 8px; padding: 6px 10px; }}
        QComboBox:focus {{ border: 1px solid {acc}; }}
        QComboBox QAbstractItemView {{ background: #171a21; color: #eaeef2; selection-background-color: {acc}; selection-color: white; border: 1px solid #232833; }}
        QMenu {{ background: #171a21; color: #eaeef2; border: 1px solid #232833; }}
        QMenu::item {{ padding: 6px 18px 6px 18px; }}
        QMenu::item:selected {{ background: {acc}; color: white; }}
        QMenu::separator {{ height: 1px; background: #232833; margin: 4px 6px; }}
        QProgressBar {{ background: #171a21; border: 1px solid #232833; border-radius: 8px; text-align: center; color: #eaeef2; }}
        QProgressBar::chunk {{ background-color: {acc}; border-radius: 8px; }}
        """

    def _light_stylesheet(self, accent: QColor) -> str:
        acc = accent.name()
        return f"""
        QMainWindow {{ background: #ffffff; color: #0f1115; }}
        #leftPane {{ background: #f6f7f9; border-right: 1px solid #e5e7eb; }}
        #leftTitle {{ color: #374151; font-size: 14px; font-weight: 700; padding: 8px 4px; }}
        QToolTip {{ color: #0f1115; background: #f3f5f7; border: 1px solid #e5e7eb; }}
        QLineEdit {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 6px 10px; color: #0f1115; }}
        QLineEdit:focus {{ border: 1px solid {acc}; box-shadow: 0 0 0 2px {acc}22; }}
        QPushButton {{ background: #ffffff; border: 1px solid #e5e7eb; color: #0f1115; border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
        QPushButton:hover {{ background: #f5f7fb; }}
        QPushButton:pressed {{ background: #eef2f7; }}
        QPushButton:focus {{ outline: none; border: 1px solid {acc}; }}
        QTabBar::tab {{ background: #ffffff; color: #0f1115; padding: 8px 14px; border: 1px solid #e5e7eb; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 6px; }}
        QTabBar::tab:selected {{ background: #f5f7fb; border-color: {acc}; }}
        QTabWidget::pane {{ border: 1px solid #e5e7eb; top: -0.2em; }}
        QGroupBox {{ border: 1px solid #e5e7eb; border-radius: 10px; margin-top: 16px; }}
        QGroupBox::title {{ left: 12px; padding: 0 4px; color: #374151; }}
        QTableWidget {{ background: #ffffff; gridline-color: #e5e7eb; color: #0f1115; alternate-background-color: #f8fafc; border: 1px solid #e5e7eb; border-radius: 8px; }}
        QHeaderView::section {{ background: #f3f4f6; color: #0f1115; border: 0px; padding: 6px; }}
        QTableWidget::item:selected {{ background: {acc}; color: white; }}
        QComboBox {{ background: #ffffff; color: #0f1115; border: 1px solid #e5e7eb; border-radius: 8px; padding: 6px 10px; }}
        QComboBox:focus {{ border: 1px solid {acc}; }}
        QComboBox QAbstractItemView {{ background: #ffffff; color: #0f1115; selection-background-color: {acc}; selection-color: white; border: 1px solid #e5e7eb; }}
        QMenu {{ background: #ffffff; color: #0f1115; border: 1px solid #e5e7eb; }}
        QMenu::item {{ padding: 6px 18px 6px 18px; }}
        QMenu::item:selected {{ background: {acc}; color: white; }}
        QMenu::separator {{ height: 1px; background: #e5e7eb; margin: 4px 6px; }}
        QProgressBar {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; text-align: center; color: #0f1115; }}
        QProgressBar::chunk {{ background-color: {acc}; border-radius: 8px; }}
        """
