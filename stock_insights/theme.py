"""theme.py — colour tokens, fonts and the global widget stylesheet.

One source of truth for how the desktop app looks:

* ``_THEMES`` holds the token sets (light + dark) for every selectable theme.
  "Default" is the Harbor palette from ``docs/design/design-system.md``; the
  other eight keep their own palettes but expose the same token names.
* ``ThemeManager`` picks the active token set (theme + light/dark mode),
  installs a QPalette + QSS on the QApplication and main window, polls the OS
  light/dark setting, and emits ``themeApplied`` so the QML ThemeController
  (qml_bridge.py) can refresh its bound tokens.
* ``resolve_fonts()`` picks the UI / display font families once via
  QFontDatabase (Segoe UI Variable Text/Display -> Segoe UI -> default).

Qt widget dialogs owned by other modules rely on the QSS generated here, so
selectors and object names (#leftPane, #watchTable, #menuStatusCorner, ...)
must stay stable.
"""

import ctypes
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QTimer, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

if sys.platform.startswith("win"):
    import winreg

# ---------------------------------------------------------------------------
# Named theme colour tokens
# ---------------------------------------------------------------------------
# Every theme provides, for both "light" and "dark":
#   bg, card, card2, text, text_muted, border   — surfaces and text
#   primary, text_on_color                      — interactive accent + text on it
#   button, secondary                           — widget button fill, selection
#   good, bad                                   — gain / loss text (contrast on card)
#   pace                                        — goal pace marker (QML only, never text)
#   focus                                       — 2 px focus ring in widget dialogs
# `pace` and `focus` are derived below for themes that don't set them.

_HARBOR = {
    "light": {
        "bg": "#E8ECEF",
        "card": "#F8FAFB",
        "card2": "#EEF2F5",
        "text": "#15202B",
        "text_muted": "#566472",
        "border": "#D3DAE0",
        "primary": "#2C55C9",
        "text_on_color": "#FFFFFF",
        "pace": "#B07610",
        "good": "#0B7A5C",
        "bad": "#B83A2E",
        # Widget-only helpers: secondary buttons sit on card2, selection and
        # focus reuse the primary accent.
        "button": "#EEF2F5",
        "secondary": "#2C55C9",
        "focus": "#2C55C9",
    },
    "dark": {
        "bg": "#161D24",
        "card": "#1F2830",
        "card2": "#27323C",
        "text": "#E4EAF0",
        "text_muted": "#93A2B0",
        "border": "#33404B",
        "primary": "#7FA2FF",
        "text_on_color": "#0E1620",
        "pace": "#F0B43C",
        "good": "#4CC9A0",
        "bad": "#FF7B6B",
        "button": "#27323C",
        "secondary": "#7FA2FF",
        "focus": "#7FA2FF",
    },
}

_THEMES: dict = {
    "Default": _HARBOR,

    "Warm Earth": {
        "light": {
            "bg": "#c0b6ac",
            "card": "#ffffff",
            "card2": "#f5f5f5",
            "text": "#2e2a2b",  # was #585253 — darkened for 7.1:1 contrast
            "text_muted": "#6f6869",
            "button": "#c9d9a8",
            "primary": "#c9d9a8",
            "secondary": "#809150",
            "text_on_color": "#161e00",
            "border": "#9da09b",
            "good": "#4a6820",  # 6.4:1 on white card
            "bad": "#892020",  # 9.2:1 on white card
        },
        "dark": {
            "bg": "#3c3835",  # darkened from #4a4545 for better bad contrast
            "card": "#47433f",
            "card2": "#524e4a",
            "text": "#e1e4de",  # 9.0:1 on card
            "text_muted": "#b0b3ae",
            "button": "#5a5548",
            "primary": "#d6e6b4",
            "secondary": "#a8c070",
            "text_on_color": "#1a1c10",
            "border": "#5e5a57",
            "good": "#b0e060",  # 7.6:1 on card
            "bad": "#ff6060",  # 3.9:1 on card (large bold text ≥3.0 OK)
        },
    },

    "Forest": {
        "light": {
            "bg": "#ecefe9",
            "card": "#f3f6f0",
            "card2": "#e5e8e2",
            "text": "#3a3d38",
            "text_muted": "#898b86",
            "button": "#d0dece",
            "primary": "#709674",
            "secondary": "#679288",
            "text_on_color": "#06210b",
            "border": "#c4c7c1",
            "good": "#285a2e",  # 7.4:1 on card
            "bad": "#8a2020",  # 8.3:1 on card
        },
        "dark": {
            "bg": "#3e403b",
            "card": "#4a4c47",
            "card2": "#525450",
            "text": "#d6d9d3",
            "text_muted": "#9da09b",
            "button": "#3d5c42",
            "primary": "#bfe8c2",
            "secondary": "#679288",
            "text_on_color": "#06210b",  # dark on light primary #bfe8c2
            "border": "#686b65",
            "good": "#90e870",  # 5.8:1 on card
            "bad": "#ffaa88",  # 4.7:1 on card
        },
    },

    "Lavender Mist": {
        "light": {
            "bg": "#f2f5ef",
            "card": "#f3f6f0",
            "card2": "#ecefe9",
            "text": "#3a3c38",  # was #747772 — darkened for 10.1:1 contrast
            "text_muted": "#90938e",
            "button": "#ddd5db",
            "primary": "#a18898",
            "secondary": "#a48c8e",
            "text_on_color": "#251420",
            "border": "#dee1db",
            "good": "#384a2a",  # 8.8:1 on card
            "bad": "#6a2848",  # 9.6:1 on card
        },
        "dark": {
            "bg": "#504e4c",  # darkened from #606360 for better contrast
            "card": "#5c5a58",
            "card2": "#676563",
            "text": "#e8e9e6",  # 6.8:1 on card
            "text_muted": "#b4b7b1",
            "button": "#6a5a65",
            "primary": "#c9b3c3",
            "secondary": "#a48c8e",
            "text_on_color": "#1e1018",  # dark on light primary #c9b3c3
            "border": "#888582",
            "good": "#d8e890",  # 6.3:1 on card
            "bad": "#f880a8",  # 3.4:1 on card (large bold ≥3.0 OK)
        },
    },

    "Slate Blue": {
        "light": {
            # text on card 4.9:1 (text darkened from source #434541 to pass card contrast)
            "bg": "#b0b3ae",
            "card": "#a7a9a4",
            "card2": "#adafaa",
            "text": "#353633",  # darkened: 5.3:1 on card
            "text_muted": "#5e605c",
            "button": "#8e9bc4",
            "primary": "#526393",
            "secondary": "#6d6187",
            "text_on_color": "#d6e4ff",
            "border": "#9ea09b",
            "good": "#0c4038",  # 4.9:1 on card
            "bad": "#4a1f48",  # 5.6:1 on card
        },
        "dark": {
            "bg": "#373934",
            "card": "#3e413c",
            "card2": "#3a3c37",
            "text": "#b8bab5",
            "text_muted": "#939590",
            "button": "#505870",
            "primary": "#6a7aa7",
            "secondary": "#80749a",
            "text_on_color": "#050a25",
            "border": "#474944",
            "good": "#7dd4c4",  # 6.0:1 on card
            "bad": "#dda0dc",  # 5.0:1 on card
        },
    },

    "Graphite": {
        "light": {
            # Graphite light: medium grey card limits P/L contrast — 3.4/4.0 acceptable for bold
            "bg": "#828580",
            "card": "#7a7c77",
            "card2": "#737671",
            "text": "#161814",
            "text_muted": "#333531",
            "button": "#4e5050",
            "primary": "#403f44",
            "secondary": "#413f41",
            "text_on_color": "#d9d3ed",
            "border": "#676a65",
            "good": "#1a2e2c",  # 3.4:1 (large bold text threshold)
            "bad": "#281820",  # 4.0:1 on card
        },
        "dark": {
            "bg": "#0a0c08",
            "card": "#10120e",
            "card2": "#0e100c",
            "text": "#868883",
            "text_muted": "#6b6e69",
            "button": "#3a393e",
            "primary": "#56555b",
            "secondary": "#585558",
            "text_on_color": "#d8d4ed",
            "border": "#171915",
            "good": "#bfdfd9",  # 13.2:1 (good-fg from source)
            "bad": "#e4d0e4",  # 13.0:1 (bad-fg from source)
        },
    },

    "Monochrome": {
        "light": {
            "bg": "#f5f5f5",
            "card": "#e8e8e8",
            "card2": "#dedede",
            "text": "#121212",
            "text_muted": "#4d4d4d",
            "button": "#c4a8e8",
            "primary": "#7553ad",
            "secondary": "#a3689f",
            "text_on_color": "#efe5ff",
            "border": "#c4c4c4",
            "good": "#007d6b",  # 4.1:1 on card (source value, large-text pass)
            "bad": "#974096",  # 4.9:1 on card
        },
        "dark": {
            "bg": "#020202",
            "card": "#060606",
            "card2": "#0b0b0b",
            "text": "#e4e4e4",
            "text_muted": "#8f8f8f",
            "button": "#5a3870",
            "primary": "#9272cc",
            "secondary": "#a3689f",
            "text_on_color": "#210b3d",
            "border": "#222222",
            "good": "#1c8d7a",  # 5.0:1 on card
            "bad": "#a84ea7",  # 4.2:1 on card (large bold acceptable)
        },
    },

    "Crimson": {
        "light": {
            "bg": "#d0d3cd",
            "card": "#bbbdb8",
            "card2": "#abada8",
            "text": "#000000",
            "text_muted": "#2a2c28",
            "button": "#9a3040",
            "primary": "#560815",
            "secondary": "#431e0f",
            "text_on_color": "#ffc3c2",
            "border": "#848681",
            "good": "#201800",  # 9.3:1 on card (source value)
            "bad": "#380014",  # 9.4:1 on card (source value)
        },
        "dark": {
            "bg": "#000000",
            "card": "#0c0808",
            "card2": "#100c0c",
            "text": "#b4b7b2",
            "text_muted": "#62645f",
            "button": "#5c2028",
            "primary": "#963c42",
            "secondary": "#7f4f3c",
            "text_on_color": "#ffc3c3",
            "border": "#1a1010",
            "good": "#9a8e60",  # 6.4:1 on card
            "bad": "#cc6080",  # 5.6:1 on card
        },
    },

    "Amber Night": {
        "light": {
            "bg": "#f3f6f0",
            "card": "#ecefe9",
            "card2": "#e5e8e2",
            "text": "#1e201c",
            "text_muted": "#82847f",
            "button": "#f0d8a0",
            "primary": "#c47c00",
            "secondary": "#8a9300",
            "text_on_color": "#2a1500",
            "border": "#dfe2dc",
            "good": "#505a00",  # 6.5:1 on card
            "bad": "#b02010",  # 5.9:1 on card
        },
        "dark": {
            "bg": "#060705",
            "card": "#191b17",
            "card2": "#272925",
            "text": "#f3f6f0",
            "text_muted": "#dfe2dc",
            "button": "#3a3300",
            "primary": "#ffcf8e",
            "secondary": "#ddea63",
            "text_on_color": "#281600",
            "border": "#595b56",
            "good": "#ffe060",  # 13.3:1 on card
            "bad": "#ff8060",  # 7.0:1 on card
        },
    },
}

# Derive the tokens older palettes don't define, so every theme exposes the
# same names (QML binds to all of them).
for _modes in _THEMES.values():
    for _t in _modes.values():
        _t.setdefault("pace", _t["secondary"])
        _t.setdefault("focus", _t["secondary"])
del _modes, _t

THEME_NAMES = list(_THEMES.keys())

# Font size presets (pt)
FONT_SIZES = {"Small": 9, "Normal": 11, "Large": 13, "X-Large": 16}
FONT_SIZE_LABELS = list(FONT_SIZES.keys())

# Shape + spacing for the widget stylesheet (Harbor: panels 10, controls 6).
_UI = {
    "panel_radius": 10,
    "card_radius": 10,
    "group_radius": 10,
    "control_radius": 6,
    "title_radius": 6,
    "splitter_radius": 2,
    "cell_hpad": 10,
    "cell_vpad": 6,
    "header_hpad": 10,
    "header_vpad": 8,
    "control_hpad": 10,
    "control_vpad": 5,
    "button_hpad": 14,
    "button_vpad": 7,
    "row_height": 32,
}

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

_TEXT_FONT_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI")
_DISPLAY_FONT_CANDIDATES = ("Segoe UI Variable Display", "Segoe UI")
_resolved_fonts: Optional[Dict[str, str]] = None


def resolve_fonts() -> Dict[str, str]:
    """Return ``{"text": family, "display": family}``, resolved once.

    Needs a QGuiApplication. Falls back to the platform's general font when
    neither Segoe family is installed (e.g. non-Windows dev machines).
    """
    global _resolved_fonts
    if _resolved_fonts is not None:
        return _resolved_fonts
    if QGuiApplication.instance() is None:
        return {"text": "", "display": ""}
    installed = set(QFontDatabase.families())
    fallback = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()

    def pick(candidates) -> str:
        return next((f for f in candidates if f in installed), fallback)

    _resolved_fonts = {"text": pick(_TEXT_FONT_CANDIDATES), "display": pick(_DISPLAY_FONT_CANDIDATES)}
    return _resolved_fonts


# ---------------------------------------------------------------------------
# Windows accessibility probes
# ---------------------------------------------------------------------------

def _windows_high_contrast_enabled() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        SPI_GETHIGHCONTRAST = 0x0042

        class HIGHCONTRAST(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                        ("lpszDefaultScheme", ctypes.c_wchar_p)]

        hc = HIGHCONTRAST()
        hc.cbSize = ctypes.sizeof(HIGHCONTRAST)
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETHIGHCONTRAST, hc.cbSize, ctypes.byref(hc), 0)
        return bool(hc.dwFlags & 0x00000001)
    except (OSError, AttributeError):
        return False


def reduce_motion_enabled() -> bool:
    """True when Windows "Show animations in Windows" is off."""
    if not sys.platform.startswith("win"):
        return False
    try:
        SPI_GETCLIENTAREAANIMATION = 0x1042
        enabled = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
        return not bool(enabled.value)
    except (OSError, AttributeError):
        return False


class ChevronProxyStyle(QProxyStyle):
    """Draw clearer chevrons for Qt arrow indicators across the app, and give
    every item view the Harbor 32 px row height."""

    _ARROW_DIRECTIONS = {
        QStyle.PrimitiveElement.PE_IndicatorArrowDown: "down",
        QStyle.PrimitiveElement.PE_IndicatorArrowUp: "up",
        QStyle.PrimitiveElement.PE_IndicatorArrowLeft: "left",
        QStyle.PrimitiveElement.PE_IndicatorArrowRight: "right",
    }

    def pixelMetric(self, metric, option=None, widget=None):
        # Table rows are vertical header sections; QHeaderView reads this
        # when it is created, so every table built after apply() gets 32 px.
        if metric == QStyle.PixelMetric.PM_HeaderDefaultSectionSizeVertical:
            return _UI["row_height"]
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        direction = self._ARROW_DIRECTIONS.get(element)
        if direction is not None and option is not None and painter is not None:
            self._draw_chevron(direction, option, painter)
            return
        super().drawPrimitive(element, option, painter, widget)

    def _draw_chevron(self, direction: str, option, painter: QPainter) -> None:
        rect = option.rect.adjusted(1, 1, -1, -1)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        span = max(4.0, min(rect.width(), rect.height()) * 0.34)
        half = span / 2.0
        center = QPointF(rect.center())

        if direction == "down":
            points = [
                QPointF(center.x() - half, center.y() - half * 0.35),
                QPointF(center.x(), center.y() + half * 0.45),
                QPointF(center.x() + half, center.y() - half * 0.35),
            ]
        elif direction == "up":
            points = [
                QPointF(center.x() - half, center.y() + half * 0.35),
                QPointF(center.x(), center.y() - half * 0.45),
                QPointF(center.x() + half, center.y() + half * 0.35),
            ]
        elif direction == "left":
            points = [
                QPointF(center.x() + half * 0.35, center.y() - half),
                QPointF(center.x() - half * 0.45, center.y()),
                QPointF(center.x() + half * 0.35, center.y() + half),
            ]
        else:
            points = [
                QPointF(center.x() - half * 0.35, center.y() - half),
                QPointF(center.x() + half * 0.45, center.y()),
                QPointF(center.x() - half * 0.35, center.y() + half),
            ]

        color = option.palette.buttonText().color()
        if not (option.state & QStyle.StateFlag.State_Enabled):
            color.setAlpha(120)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))
        painter.restore()


class ThemeManager(QObject):
    override_mode: str = "System"  # Colour Mode: System / Light / Dark
    # Kept for the Settings checkbox. Harbor (Default) uses its own fixed
    # primary, so the Windows accent no longer recolours the app.
    match_system_accent: bool = True
    theme_name: str = "Default"  # Theme: Default / Warm Earth / Forest / etc.
    font_size_label: str = "Normal"  # Font Size: Small / Normal / Large / X-Large

    # Emitted at the end of every successful apply(). Subscribers (e.g. the
    # QML ThemeController) use this to refresh their bound color tokens.
    themeApplied = Signal()

    def __init__(self, window, poll_secs: int = 3):
        super().__init__(window)
        self.win = window
        self.poll_secs = poll_secs
        self._last_state = None
        self._timer: Optional[QTimer] = None
        self._chevron_style: Optional[ChevronProxyStyle] = None
        self._fixed_light_accent = (44, 85, 201)  # Harbor primary, light
        self._fixed_dark_accent = (127, 162, 255)  # Harbor primary, dark

    def _assets_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "stock_insights" / "assets"
        return Path(__file__).resolve().parent / "assets"

    def _asset_url(self, filename: str) -> str:
        return self._assets_dir().joinpath(filename).resolve().as_posix()

    def _chevron_asset(self, direction: str) -> str:
        suffix = "dark" if self._is_light() else "light"
        return self._asset_url(f"chevron-{direction}-{suffix}.svg")

    # ---- Windows helpers ----

    def _windows_is_light(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
                return bool(v)
        except OSError:
            return False

    def _windows_accent_rgb(self) -> Tuple[int, int, int]:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent") as k:
                v, _ = winreg.QueryValueEx(k, "AccentColor")
                return v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
        except OSError:
            pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
                v, _ = winreg.QueryValueEx(k, "ColorizationColor")
                return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
        except OSError:
            pass
        try:
            color = ctypes.c_uint()
            opaque = ctypes.c_int()
            if ctypes.windll.dwmapi.DwmGetColorizationColor(ctypes.byref(color), ctypes.byref(opaque)) == 0:
                v = color.value
                return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
        except (OSError, AttributeError):
            pass
        return self._fixed_light_accent

    def _accent_for_mode(self, is_light: bool) -> Tuple[int, int, int]:
        if self.match_system_accent and sys.platform.startswith("win"):
            return self._windows_accent_rgb()
        return self._fixed_light_accent if is_light else self._fixed_dark_accent

    # ---- Public API ----

    def set_override_mode(self, mode: str):
        self.override_mode = mode if mode in ("System", "Light", "Dark") else "System"
        self.apply()

    def set_match_system_accent(self, enabled: bool):
        self.match_system_accent = bool(enabled)
        self.apply()

    def set_theme(self, name: str):
        self.theme_name = name if name in _THEMES else "Default"
        self.apply()

    def set_font_size(self, label: str):
        self.font_size_label = label if label in FONT_SIZES else "Normal"
        self._apply_font()
        # Emit so QML-side ThemeController.refresh() rebinds — without this
        # the QML scene keeps its old fontScale and visually ignores the change.
        self.themeApplied.emit()

    def _apply_font(self):
        pt = FONT_SIZES.get(self.font_size_label, 11)
        app = QApplication.instance()
        if app is not None:
            f = app.font()
            family = resolve_fonts()["text"]
            if family:
                f.setFamily(family)
            f.setPointSize(pt)
            app.setFont(f)

    def _is_light(self) -> bool:
        if self.override_mode in ("Light", "Dark"):
            return self.override_mode == "Light"
        if sys.platform.startswith("win"):
            return self._windows_is_light()
        return False

    def is_light(self) -> bool:
        """True when the light variant of the active theme is in use."""
        return self._is_light()

    def tokens(self) -> Dict[str, str]:
        """Copy of the active token dict (theme + light/dark), see _THEMES."""
        return dict(self._tokens())

    @staticmethod
    def font_families() -> Dict[str, str]:
        """``{"text": ..., "display": ...}`` resolved by resolve_fonts()."""
        return dict(resolve_fonts())

    @staticmethod
    def reduce_motion() -> bool:
        """True when the OS asks apps to skip non-essential animation."""
        return reduce_motion_enabled()

    def current_state(self) -> tuple:
        is_light = self._is_light()
        r, g, b = self._accent_for_mode(is_light)
        return is_light, r, g, b, self.match_system_accent, self.theme_name, self.font_size_label

    def start_watching(self):
        if self._timer is None:
            self._timer = QTimer(self.win)
            self._timer.setInterval(self.poll_secs * 1000)
            self._timer.timeout.connect(self._maybe_update_theme)
            self._timer.start()

    def stop_watching(self):
        """Stop the OS-theme poll timer. Call this before the window is torn
        down so a pending tick cannot repaint a dying widget."""
        if self._timer is not None:
            # stop() is enough: a stopped QTimer never fires. Disconnecting
            # here only produced a libpyside RuntimeWarning when nothing was
            # connected yet.
            self._timer.stop()

    def _maybe_update_theme(self):
        if self.current_state() != self._last_state:
            self.apply()

    def _refresh_window(self) -> None:
        refresh = getattr(self.win, "update_ui", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:  # a broken refresh hook must not break theming
                import logging
                logging.getLogger(__name__).exception("update_ui hook raised")

    def apply(self):
        if sys.platform.startswith("win") and _windows_high_contrast_enabled():
            self.win.setStyleSheet("")
            self._refresh_window()
            return

        self._last_state = self.current_state()
        tokens = self._tokens()
        palette = self._themed_palette(tokens)
        stylesheet = self._themed_stylesheet(tokens)

        app = QApplication.instance()
        if app is not None:
            if self._chevron_style is None:
                existing_style = app.style()
                self._chevron_style = existing_style if isinstance(existing_style,
                                                                   ChevronProxyStyle) else ChevronProxyStyle(
                    existing_style)
            if app.style() is not self._chevron_style:
                app.setStyle(self._chevron_style)
            app.setPalette(palette)
            app.setStyleSheet(stylesheet)

        if self._chevron_style is not None and self.win.style() is not self._chevron_style:
            self.win.setStyle(self._chevron_style)
        self.win.setPalette(palette)
        self.win.setStyleSheet(stylesheet)

        try:
            self.win.style().unpolish(self.win)
            self.win.style().polish(self.win)
        except RuntimeError:  # window already being destroyed
            pass
        self._refresh_window()
        self.win.update()
        self._apply_font()
        self.themeApplied.emit()

    # ---- Colour accessor methods used by portfolio_tab / main_window ----

    def _tokens(self) -> dict:
        """Active token dict (shared, do not mutate). Every theme, Default
        included, now has tokens — the Optional return is historical."""
        td = _THEMES.get(self.theme_name) or _THEMES["Default"]
        return td["light" if self._is_light() else "dark"]

    def profit_color(self) -> str:
        """Hex color for positive P/L text in tables — contrasts with card background."""
        return self._tokens()["good"]

    def text_color(self) -> str:
        return self._tokens()["text"]

    def border_color(self) -> str:
        return self._tokens()["border"]

    def button_color(self) -> str:
        return self._tokens()["button"]

    def selected_surface_color(self) -> str:
        return self._tokens()["primary"]

    def selected_text_color(self) -> str:
        return self._tokens()["text_on_color"]

    def focus_border_color(self) -> str:
        return self._tokens()["focus"]

    def loss_color(self) -> str:
        """Hex color for negative P/L text in tables — contrasts with card background."""
        return self._tokens()["bad"]

    def pace_color(self) -> str:
        """Goal-pace marker colour. Reserved for the pace rail / curve line."""
        return self._tokens()["pace"]

    def waiting_row_tint(self) -> Tuple[int, int, int, int]:
        """RGBA tint for WAITING/Pending order rows — a neutral wash of the
        muted text colour (amber is reserved for the goal pace marker)."""
        c = QColor(self._tokens()["text_muted"])
        return c.red(), c.green(), c.blue(), 38

    def short_row_tint(self) -> Tuple[int, int, int, int]:
        """RGBA tint for SHORT position rows — a light wash of primary."""
        c = QColor(self._tokens()["primary"])
        return c.red(), c.green(), c.blue(), 30 if self._is_light() else 40

    # ---- Palette + stylesheet builders ----

    def _themed_palette(self, t: dict) -> QPalette:
        p = QPalette()
        p.setColor(QPalette.Window, QColor(t["bg"]))
        p.setColor(QPalette.Base, QColor(t["card"]))
        p.setColor(QPalette.AlternateBase, QColor(t["card2"]))
        p.setColor(QPalette.ToolTipBase, QColor(t["card"]))
        p.setColor(QPalette.ToolTipText, QColor(t["text"]))
        p.setColor(QPalette.Text, QColor(t["text"]))
        p.setColor(QPalette.Button, QColor(t["button"]))
        p.setColor(QPalette.ButtonText, QColor(t["text"]))
        p.setColor(QPalette.Highlight, QColor(t["secondary"]))
        p.setColor(QPalette.HighlightedText, QColor(t["text_on_color"]))
        p.setColor(QPalette.WindowText, QColor(t["text"]))
        p.setColor(QPalette.PlaceholderText, QColor(t["text_muted"]))
        p.setColor(QPalette.Link, QColor(t["primary"]))
        p.setColor(QPalette.Mid, QColor(t["border"]))
        return p

    def _themed_stylesheet(self, t: dict) -> str:
        """Global QSS for widget dialogs. No shadows; panels 10, controls 6;
        focus is a 2 px ring in `focus` (padding shrinks by 1 px on focus so
        the content does not jump)."""
        bg = t["bg"]
        card = t["card"]
        card2 = t["card2"]
        text = t["text"]
        muted = t["text_muted"]
        btn = t["button"]
        pri = t["primary"]
        brd = t["border"]
        toc = t["text_on_color"]
        foc = t["focus"]
        u = _UI
        cr = u["control_radius"]
        cvp, chp = u["control_vpad"], u["control_hpad"]
        bvp, bhp = u["button_vpad"], u["button_hpad"]
        chevron_down = self._chevron_asset("down")
        chevron_up = self._chevron_asset("up")
        return f"""
        QMainWindow {{ background: {bg}; color: {text}; }}
        QWidget {{ background: {card}; color: {text}; }}
        #leftPane {{ background: {bg}; border: 1px solid {brd}; border-radius: {u["panel_radius"]}px; }}
        #leftTitle {{ color: {muted}; font-size: 14px; font-weight: 600; padding: 4px 2px; }}
        #watchTableCard {{ background: {card}; border: 1px solid {brd}; border-radius: {u["card_radius"]}px; }}
        #watchTable {{ background: transparent; border: none; border-radius: {u["card_radius"]}px;
                       selection-background-color: {pri}; selection-color: {toc}; }}
        #watchTable::item {{ padding: 0px {u["cell_hpad"]}px; border-bottom: 1px solid {brd}; }}
        #watchTable::item:selected {{ background: {pri}; color: {toc}; }}
        #watchTable QHeaderView {{ background: transparent; border: none; }}
        #watchTable QHeaderView::section {{ background: {card2}; color: {muted};
                                           border: none; border-bottom: 1px solid {brd};
                                           padding: {u["header_vpad"]}px {u["header_hpad"]}px; font-weight: 600; }}
        #watchTable QHeaderView::section:first {{ border-top-left-radius: {u["card_radius"]}px; }}
        #watchTable QHeaderView::section:last {{ border-top-right-radius: {u["card_radius"]}px; }}
        QToolTip {{ color: {text}; background: {card}; border: 1px solid {brd}; border-radius: {cr}px; padding: 4px 6px; }}
        QDialog {{ background: {bg}; }}
        QScrollArea {{ background: {bg}; border: none; }}
        QScrollArea > QWidget > QWidget {{ background: {bg}; }}
        QLineEdit, QPlainTextEdit, QTextEdit {{ background: {card}; border: 1px solid {brd}; border-radius: {cr}px;
                     padding: {cvp}px {chp}px; color: {text};
                     selection-background-color: {pri}; selection-color: {toc}; }}
        QLineEdit {{ min-height: 22px; }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 2px solid {foc}; padding: {cvp - 1}px {chp - 1}px; }}
        QPushButton {{ background: {btn}; border: 1px solid {brd}; color: {text};
                       border-radius: {cr}px; padding: {bvp}px {bhp}px; font-weight: 600; min-height: 18px; }}
        QPushButton:hover {{ background: {card2}; border-color: {muted}; }}
        QPushButton:pressed {{ background: {brd}; }}
        QPushButton:default {{ background: {pri}; border-color: {pri}; color: {toc}; }}
        QPushButton:focus {{ outline: none; border: 2px solid {foc}; padding: {bvp - 1}px {bhp - 1}px; }}
        QPushButton:disabled {{ color: {muted}; }}
        QPushButton:default:disabled {{ background: {card2}; border-color: {brd}; color: {muted}; }}
        QPushButton:checked {{ background: {pri}; border-color: {pri}; color: {toc}; }}
        QPushButton[flat="true"] {{ background: transparent; border: none; color: {muted}; }}
        QTabBar::tab {{ background: transparent; color: {muted}; padding: 8px 14px;
                        border: none; border-bottom: 2px solid transparent;
                        margin-right: 4px; margin-top: 0px; font-weight: 600; }}
        QTabBar::tab:hover {{ color: {text}; }}
        QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {pri}; }}
        QTabWidget::pane {{ border: 1px solid {brd}; border-radius: {u["card_radius"]}px;
                            margin-top: 0px; top: -1px; background: {card}; }}
        QGroupBox {{ border: 1px solid {brd}; border-radius: {u["group_radius"]}px; margin-top: 16px;
                     background: {card}; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 2px 6px;
                            color: {muted}; background: transparent; font-weight: 600; }}
        QTableWidget, QTableView, QTreeView, QListView {{ background: {card}; gridline-color: {brd}; color: {text};
                        alternate-background-color: {card2}; border: 1px solid {brd};
                        border-radius: {cr}px; selection-background-color: {pri}; selection-color: {toc}; }}
        QTreeView::item, QListView::item {{ min-height: {u["row_height"]}px; }}
        QHeaderView::section {{ background: {card2}; color: {muted}; border: 0px; border-bottom: 1px solid {brd};
                                padding: {u["cell_vpad"]}px {u["cell_hpad"]}px; font-weight: 600; }}
        QTableCornerButton::section {{ background: {card2}; border: 0px; border-top-left-radius: {cr}px; }}
        QTableWidget::item:selected, QTableView::item:selected {{ background: {pri}; color: {toc}; }}
        QComboBox {{ background: {card}; color: {text}; border: 1px solid {brd};
                     border-radius: {cr}px; padding: {cvp}px 34px {cvp}px {chp}px; min-height: 22px; }}
        QComboBox:focus {{ border: 2px solid {foc}; padding: {cvp - 1}px 33px {cvp - 1}px {chp - 1}px; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 26px; background: transparent; border: none;
        }}
        QComboBox::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
        QComboBox QAbstractItemView {{ background: {card}; color: {text};
            selection-background-color: {pri}; selection-color: {toc};
            border: 1px solid {brd}; border-radius: {cr}px; outline: none; }}
        QSpinBox, QDoubleSpinBox {{ background: {card}; color: {text}; border: 1px solid {brd};
                                    border-radius: {cr}px; padding: {cvp}px 32px {cvp}px {chp}px; min-height: 22px; }}
        QSpinBox:focus, QDoubleSpinBox:focus {{ border: 2px solid {foc}; padding: {cvp - 1}px 31px {cvp - 1}px {chp - 1}px; }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border; subcontrol-position: top right;
            width: 22px; background: {card2}; border-left: 1px solid {brd};
            border-bottom: 1px solid {brd}; border-top-right-radius: {cr}px;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border; subcontrol-position: bottom right;
            width: 22px; background: {card2}; border-left: 1px solid {brd};
            border-bottom-right-radius: {cr}px;
        }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {brd}; }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url("{chevron_up}"); width: 12px; height: 12px;
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url("{chevron_down}"); width: 12px; height: 12px;
        }}
        QDateEdit {{ background: {card}; color: {text}; border: 1px solid {brd};
                     border-radius: {cr}px; padding: {cvp}px 34px {cvp}px {chp}px; min-height: 22px; }}
        QDateEdit:focus {{ border: 2px solid {foc}; padding: {cvp - 1}px 33px {cvp - 1}px {chp - 1}px; }}
        QDateEdit::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 26px; background: transparent; border: none;
        }}
        QDateEdit::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
        QCheckBox, QRadioButton {{ color: {text}; spacing: 8px; background: transparent; border: none; }}
        QCheckBox::indicator {{ border: 1px solid {muted}; border-radius: 4px;
                                background: {card}; width: 16px; height: 16px; }}
        QCheckBox::indicator:checked {{ background: {pri}; border-color: {pri}; }}
        QCheckBox:focus {{ outline: none; }}
        QCheckBox::indicator:focus {{ border: 2px solid {foc}; }}
        QMenu {{ background: {card}; color: {text}; border: 1px solid {brd}; border-radius: {cr}px; padding: 4px; }}
        QMenu::item {{ padding: 7px 18px 7px 14px; border-radius: 4px; }}
        QMenu::item:selected {{ background: {card2}; color: {text}; }}
        QMenu::item:disabled {{ color: {muted}; }}
        QMenu::separator {{ height: 1px; background: {brd}; margin: 4px 6px; }}
        QProgressBar {{ background: {card2}; border: none; border-radius: {cr}px;
                        text-align: center; color: {text}; }}
        QProgressBar::chunk {{ background-color: {pri}; border-radius: {cr}px; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {brd}; border-radius: 3px; min-height: 24px; }}
        QScrollBar::handle:vertical:hover {{ background: {muted}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {brd}; border-radius: 3px; min-width: 24px; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
        QSplitter::handle {{ background: {brd}; border-radius: {u["splitter_radius"]}px; margin: 4px 2px; }}
        QStatusBar {{ background: {bg}; color: {muted}; }}
        QMenuBar {{ background: {bg}; color: {text}; border-bottom: 1px solid {brd}; padding-bottom: 2px; }}
        QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; }}
        QMenuBar::item:selected {{ background: {card2}; color: {text}; }}
        #menuStatusCorner {{ background: {bg}; border: none; }}
        #menuStatusCorner QLabel {{ background: transparent; padding: 0px; border: none; text-decoration: none; }}
        QLabel {{ color: {text}; background: transparent; }}
        QLabel:disabled {{ color: {muted}; }}
        QFrame[role="panel"] {{ border-radius: 10px; }}
        """
