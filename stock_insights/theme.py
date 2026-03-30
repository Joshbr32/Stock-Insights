from __future__ import annotations

"""Application theme management.

The manager reads Windows system theme and accent state when available and then
builds one app-wide palette + stylesheet. The stylesheet is assembled from
shared component builders so light/dark themes stay consistent and easier to
maintain.
"""

import ctypes
import sys
from typing import Optional, Tuple

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

if sys.platform.startswith("win"):
    import winreg


DEFAULT_ACCENT_RGB = (0, 120, 215)


def _windows_high_contrast_enabled() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        spi_get_high_contrast = 0x0042

        class HIGHCONTRAST(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("dwFlags", ctypes.c_uint),
                ("lpszDefaultScheme", ctypes.c_wchar_p),
            ]

        hc = HIGHCONTRAST()
        hc.cbSize = ctypes.sizeof(HIGHCONTRAST)
        ctypes.windll.user32.SystemParametersInfoW(
            spi_get_high_contrast,
            hc.cbSize,
            ctypes.byref(hc),
            0,
        )
        hcf_high_contrast_on = 0x00000001
        return bool(hc.dwFlags & hcf_high_contrast_on)
    except Exception:
        return False


class ThemeManager(QObject):
    """Applies and watches the application theme state."""

    override_mode: str = "System"  # valid values: System | Light | Dark

    def __init__(self, window, poll_secs: int = 3):
        super().__init__(window)
        self.win = window
        self.poll_secs = poll_secs
        self._last_state: Optional[tuple] = None
        self._timer: Optional[QTimer] = None

    def _windows_is_light(self) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return bool(value)
        except Exception:
            return False

    def _windows_accent_rgb(self) -> Tuple[int, int, int]:
        # Try Explorer\Accent first.
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AccentColor")
                return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)
        except Exception:
            pass

        # Fall back to DWM.
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
                value, _ = winreg.QueryValueEx(key, "ColorizationColor")
                return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
        except Exception:
            pass

        # Last resort: DwmGetColorizationColor.
        try:
            color = ctypes.c_uint()
            opaque_blend = ctypes.c_int()
            if ctypes.windll.dwmapi.DwmGetColorizationColor(
                ctypes.byref(color),
                ctypes.byref(opaque_blend),
            ) == 0:
                value = color.value  # AARRGGBB
                return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
        except Exception:
            pass

        return DEFAULT_ACCENT_RGB

    def current_state(self) -> tuple:
        if self.override_mode in ("Light", "Dark"):
            is_light = self.override_mode == "Light"
            r, g, b = self._windows_accent_rgb() if sys.platform.startswith("win") else DEFAULT_ACCENT_RGB
            return (is_light, r, g, b)

        if sys.platform.startswith("win"):
            is_light = self._windows_is_light()
            r, g, b = self._windows_accent_rgb()
        else:
            is_light = False
            r, g, b = DEFAULT_ACCENT_RGB
        return (is_light, r, g, b)

    def set_override_mode(self, mode: str) -> None:
        self.override_mode = mode if mode in ("System", "Light", "Dark") else "System"
        self.apply()

    def start_watching(self) -> None:
        if self._timer is None:
            self._timer = QTimer(self.win)
            self._timer.setInterval(self.poll_secs * 1000)
            self._timer.timeout.connect(self._maybe_update_theme)
            self._timer.start()

    def _maybe_update_theme(self) -> None:
        state = self.current_state()
        if state != self._last_state:
            self.apply()

    def apply(self) -> None:
        if sys.platform.startswith("win") and _windows_high_contrast_enabled():
            self.win.setStyleSheet("")
            return

        is_light, r, g, b = self.current_state()
        self._last_state = (is_light, r, g, b)
        accent = QColor(r, g, b)

        palette = self._light_palette(accent) if is_light else self._dark_palette(accent)
        stylesheet = self._build_stylesheet(accent, is_light=is_light)

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
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#0f1115"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#14171d"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#171a21"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#10131a"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#eaeef2"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#eaeef2"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#1f2430"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#eaeef2"))
        palette.setColor(QPalette.ColorRole.Highlight, accent)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#eaeef2"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#a9b1bd"))
        return palette

    def _light_palette(self, accent: QColor) -> QPalette:
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#f8fafc"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#eef2f7"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#f3f5f7"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#0f1115"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#0f1115"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#0f1115"))
        palette.setColor(QPalette.ColorRole.Highlight, accent)
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#0f1115"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#4b5563"))
        return palette

    def _build_stylesheet(self, accent: QColor, *, is_light: bool) -> str:
        theme = self._theme_tokens(accent, is_light=is_light)
        return "\n".join(
            [
                self._window_rules(theme),
                self._input_rules(theme),
                self._tab_rules(theme),
                self._group_rules(theme),
                self._table_rules(theme),
                self._combo_rules(theme),
                self._menu_rules(theme),
                self._progress_rules(theme),
            ]
        )

    def _theme_tokens(self, accent: QColor, *, is_light: bool) -> dict[str, str]:
        if is_light:
            return {
                "accent": accent.name(),
                "window": "#ffffff",
                "left_pane": "#f6f7f9",
                "left_border": "#e5e7eb",
                "title": "#374151",
                "tooltip": "#f3f5f7",
                "text": "#0f1115",
                "input_bg": "#ffffff",
                "input_border": "#e5e7eb",
                "button_bg": "#ffffff",
                "button_hover": "#f5f7fb",
                "button_pressed": "#eef2f7",
                "tab_bg": "#ffffff",
                "tab_selected": "#f5f7fb",
                "group_border": "#e5e7eb",
                "table_alt": "#f8fafc",
                "header_bg": "#f3f4f6",
            }
        return {
            "accent": accent.name(),
            "window": "#0f1115",
            "left_pane": "#10131a",
            "left_border": "#232833",
            "title": "#a9b1bd",
            "tooltip": "#10131a",
            "text": "#eaeef2",
            "input_bg": "#171a21",
            "input_border": "#232833",
            "button_bg": "#1f2430",
            "button_hover": "#262d3a",
            "button_pressed": "#2b3240",
            "tab_bg": "#171a21",
            "tab_selected": "#1f2430",
            "group_border": "#232833",
            "table_alt": "#14171d",
            "header_bg": "#171a21",
        }

    @staticmethod
    def _window_rules(theme: dict[str, str]) -> str:
        return f"""
        QMainWindow {{ background: {theme['window']}; color: {theme['text']}; }}
        #leftPane {{ background: {theme['left_pane']}; border-right: 1px solid {theme['left_border']}; }}
        #leftTitle {{ color: {theme['title']}; font-size: 14px; font-weight: 700; padding: 8px 4px; }}
        QToolTip {{ color: {theme['text']}; background: {theme['tooltip']}; border: 1px solid {theme['left_border']}; }}
        """

    @staticmethod
    def _input_rules(theme: dict[str, str]) -> str:
        return f"""
        QLineEdit {{ background: {theme['input_bg']}; border: 1px solid {theme['input_border']}; border-radius: 8px; padding: 6px 10px; color: {theme['text']}; }}
        QLineEdit:focus {{ border: 1px solid {theme['accent']}; }}
        QPushButton {{ background: {theme['button_bg']}; border: 1px solid {theme['input_border']}; color: {theme['text']}; border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
        QPushButton:hover {{ background: {theme['button_hover']}; }}
        QPushButton:pressed {{ background: {theme['button_pressed']}; }}
        QPushButton:focus {{ outline: none; border: 1px solid {theme['accent']}; }}
        """

    @staticmethod
    def _tab_rules(theme: dict[str, str]) -> str:
        return f"""
        QTabBar::tab {{ background: {theme['tab_bg']}; color: {theme['text']}; padding: 8px 14px; border: 1px solid {theme['left_border']}; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 6px; }}
        QTabBar::tab:selected {{ background: {theme['tab_selected']}; border-color: {theme['accent']}; }}
        QTabWidget::pane {{ border: 1px solid {theme['left_border']}; top: -0.2em; }}
        """

    @staticmethod
    def _group_rules(theme: dict[str, str]) -> str:
        return f"""
        QGroupBox {{ border: 1px solid {theme['group_border']}; border-radius: 10px; margin-top: 16px; }}
        QGroupBox::title {{ left: 12px; padding: 0 4px; color: {theme['title']}; }}
        """

    @staticmethod
    def _table_rules(theme: dict[str, str]) -> str:
        return f"""
        QTableWidget {{ background: {theme['window']}; gridline-color: {theme['group_border']}; color: {theme['text']}; alternate-background-color: {theme['table_alt']}; border: 1px solid {theme['group_border']}; border-radius: 8px; }}
        QHeaderView::section {{ background: {theme['header_bg']}; color: {theme['text']}; border: 0px; padding: 6px; }}
        QTableWidget::item:selected {{ background: {theme['accent']}; color: white; }}
        """

    @staticmethod
    def _combo_rules(theme: dict[str, str]) -> str:
        return f"""
        QComboBox {{ background: {theme['input_bg']}; color: {theme['text']}; border: 1px solid {theme['input_border']}; border-radius: 8px; padding: 6px 10px; }}
        QComboBox:focus {{ border: 1px solid {theme['accent']}; }}
        QComboBox QAbstractItemView {{ background: {theme['input_bg']}; color: {theme['text']}; selection-background-color: {theme['accent']}; selection-color: white; border: 1px solid {theme['input_border']}; }}
        """

    @staticmethod
    def _menu_rules(theme: dict[str, str]) -> str:
        return f"""
        QMenu {{ background: {theme['input_bg']}; color: {theme['text']}; border: 1px solid {theme['input_border']}; }}
        QMenu::item {{ padding: 6px 18px 6px 18px; }}
        QMenu::item:selected {{ background: {theme['accent']}; color: white; }}
        QMenu::separator {{ height: 1px; background: {theme['group_border']}; margin: 4px 6px; }}
        """

    @staticmethod
    def _progress_rules(theme: dict[str, str]) -> str:
        return f"""
        QProgressBar {{ background: {theme['input_bg']}; border: 1px solid {theme['input_border']}; border-radius: 8px; text-align: center; color: {theme['text']}; }}
        QProgressBar::chunk {{ background-color: {theme['accent']}; border-radius: 8px; }}
        """
