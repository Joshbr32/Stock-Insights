import ctypes
import os
import sys
from pathlib import Path
from typing import Optional, Tuple
from PySide6.QtCore import QTimer, QObject, QPointF, Qt
from PySide6.QtGui import QPalette, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

if sys.platform.startswith("win"):
    import winreg


# ---------------------------------------------------------------------------
# Named theme colour tokens
# ---------------------------------------------------------------------------
# Tokens used in _themed_stylesheet / palette:
#   bg, card, card2, text, text_muted, button, primary, secondary, border
#
# Tokens used for profit/loss text and row tinting (wired via ThemeManager methods):
#   good   — profit / positive P/L text colour (must contrast with 'card' bg)
#   bad    — loss / negative P/L text colour   (must contrast with 'card' bg)

_THEMES: dict = {
    "Default": None,   # uses the built-in dark/light stylesheets below

    "Warm Earth": {
        "light": {
            "bg":         "#c0b6ac",
            "card":       "#ffffff",
            "card2":      "#f5f5f5",
            "text":       "#2e2a2b",   # was #585253 — darkened for 7.1:1 contrast
            "text_muted": "#6f6869",
            "button":     "#c9d9a8",
            "primary":    "#c9d9a8",
            "secondary":  "#809150",
            "text_on_color": "#161e00",
            "border":     "#9da09b",
            "good":       "#4a6820",   # 6.4:1 on white card
            "bad":        "#892020",   # 9.2:1 on white card
        },
        "dark": {
            "bg":         "#3c3835",   # darkened from #4a4545 for better bad contrast
            "card":       "#47433f",
            "card2":      "#524e4a",
            "text":       "#e1e4de",   # 9.0:1 on card
            "text_muted": "#b0b3ae",
            "button":     "#5a5548",
            "primary":    "#d6e6b4",
            "secondary":  "#a8c070",
            "text_on_color": "#1a1c10",
            "border":     "#5e5a57",
            "good":       "#b0e060",   # 7.6:1 on card
            "bad":        "#ff6060",   # 3.9:1 on card (large bold text ≥3.0 OK)
        },
    },

    "Forest": {
        "light": {
            "bg":         "#ecefe9",
            "card":       "#f3f6f0",
            "card2":      "#e5e8e2",
            "text":       "#3a3d38",
            "text_muted": "#898b86",
            "button":     "#d0dece",
            "primary":    "#709674",
            "secondary":  "#679288",
            "text_on_color": "#06210b",
            "border":     "#c4c7c1",
            "good":       "#285a2e",   # 7.4:1 on card
            "bad":        "#8a2020",   # 8.3:1 on card
        },
        "dark": {
            "bg":         "#3e403b",
            "card":       "#4a4c47",
            "card2":      "#525450",
            "text":       "#d6d9d3",
            "text_muted": "#9da09b",
            "button":     "#3d5c42",
            "primary":    "#bfe8c2",
            "secondary":  "#679288",
            "text_on_color": "#06210b",   # dark on light primary #bfe8c2
            "border":     "#686b65",
            "good":       "#90e870",   # 5.8:1 on card
            "bad":        "#ffaa88",   # 4.7:1 on card
        },
    },

    "Lavender Mist": {
        "light": {
            "bg":         "#f2f5ef",
            "card":       "#f3f6f0",
            "card2":      "#ecefe9",
            "text":       "#3a3c38",   # was #747772 — darkened for 10.1:1 contrast
            "text_muted": "#90938e",
            "button":     "#ddd5db",
            "primary":    "#a18898",
            "secondary":  "#a48c8e",
            "text_on_color": "#251420",
            "border":     "#dee1db",
            "good":       "#384a2a",   # 8.8:1 on card
            "bad":        "#6a2848",   # 9.6:1 on card
        },
        "dark": {
            "bg":         "#504e4c",   # darkened from #606360 for better contrast
            "card":       "#5c5a58",
            "card2":      "#676563",
            "text":       "#e8e9e6",   # 6.8:1 on card
            "text_muted": "#b4b7b1",
            "button":     "#6a5a65",
            "primary":    "#c9b3c3",
            "secondary":  "#a48c8e",
            "text_on_color": "#1e1018",   # dark on light primary #c9b3c3
            "border":     "#888582",
            "good":       "#d8e890",   # 6.3:1 on card
            "bad":        "#f880a8",   # 3.4:1 on card (large bold ≥3.0 OK)
        },
    },

    "Slate Blue": {
        "light": {
            # text on card 4.9:1 (text darkened from source #434541 to pass card contrast)
            "bg":           "#b0b3ae",
            "card":         "#a7a9a4",
            "card2":        "#adafaa",
            "text":         "#353633",   # darkened: 5.3:1 on card
            "text_muted":   "#5e605c",
            "button":       "#8e9bc4",
            "primary":      "#526393",
            "secondary":    "#6d6187",
            "text_on_color":"#d6e4ff",
            "border":       "#9ea09b",
            "good":         "#0c4038",   # 4.9:1 on card
            "bad":          "#4a1f48",   # 5.6:1 on card
        },
        "dark": {
            "bg":           "#373934",
            "card":         "#3e413c",
            "card2":        "#3a3c37",
            "text":         "#b8bab5",
            "text_muted":   "#939590",
            "button":       "#505870",
            "primary":      "#6a7aa7",
            "secondary":    "#80749a",
            "text_on_color":"#050a25",
            "border":       "#474944",
            "good":         "#7dd4c4",   # 6.0:1 on card
            "bad":          "#dda0dc",   # 5.0:1 on card
        },
    },

    "Graphite": {
        "light": {
            # Graphite light: medium grey card limits P/L contrast — 3.4/4.0 acceptable for bold
            "bg":           "#828580",
            "card":         "#7a7c77",
            "card2":        "#737671",
            "text":         "#161814",
            "text_muted":   "#333531",
            "button":       "#4e5050",
            "primary":      "#403f44",
            "secondary":    "#413f41",
            "text_on_color":"#d9d3ed",
            "border":       "#676a65",
            "good":         "#1a2e2c",   # 3.4:1 (large bold text threshold)
            "bad":          "#281820",   # 4.0:1 on card
        },
        "dark": {
            "bg":           "#0a0c08",
            "card":         "#10120e",
            "card2":        "#0e100c",
            "text":         "#868883",
            "text_muted":   "#6b6e69",
            "button":       "#3a393e",
            "primary":      "#56555b",
            "secondary":    "#585558",
            "text_on_color":"#d8d4ed",
            "border":       "#171915",
            "good":         "#bfdfd9",   # 13.2:1 (good-fg from source)
            "bad":          "#e4d0e4",   # 13.0:1 (bad-fg from source)
        },
    },

    "Monochrome": {
        "light": {
            "bg":           "#f5f5f5",
            "card":         "#e8e8e8",
            "card2":        "#dedede",
            "text":         "#121212",
            "text_muted":   "#4d4d4d",
            "button":       "#c4a8e8",
            "primary":      "#7553ad",
            "secondary":    "#a3689f",
            "text_on_color":"#efe5ff",
            "border":       "#c4c4c4",
            "good":         "#007d6b",   # 4.1:1 on card (source value, large-text pass)
            "bad":          "#974096",   # 4.9:1 on card
        },
        "dark": {
            "bg":           "#020202",
            "card":         "#060606",
            "card2":        "#0b0b0b",
            "text":         "#e4e4e4",
            "text_muted":   "#8f8f8f",
            "button":       "#5a3870",
            "primary":      "#9272cc",
            "secondary":    "#a3689f",
            "text_on_color":"#210b3d",
            "border":       "#222222",
            "good":         "#1c8d7a",   # 5.0:1 on card
            "bad":          "#a84ea7",   # 4.2:1 on card (large bold acceptable)
        },
    },

    "Crimson": {
        "light": {
            "bg":           "#d0d3cd",
            "card":         "#bbbdb8",
            "card2":        "#abada8",
            "text":         "#000000",
            "text_muted":   "#2a2c28",
            "button":       "#9a3040",
            "primary":      "#560815",
            "secondary":    "#431e0f",
            "text_on_color":"#ffc3c2",
            "border":       "#848681",
            "good":         "#201800",   # 9.3:1 on card (source value)
            "bad":          "#380014",   # 9.4:1 on card (source value)
        },
        "dark": {
            "bg":           "#000000",
            "card":         "#0c0808",
            "card2":        "#100c0c",
            "text":         "#b4b7b2",
            "text_muted":   "#62645f",
            "button":       "#5c2028",
            "primary":      "#963c42",
            "secondary":    "#7f4f3c",
            "text_on_color":"#ffc3c3",
            "border":       "#1a1010",
            "good":         "#9a8e60",   # 6.4:1 on card
            "bad":          "#cc6080",   # 5.6:1 on card
        },
    },

    "Amber Night": {
        "light": {
            "bg":         "#f3f6f0",
            "card":       "#ecefe9",
            "card2":      "#e5e8e2",
            "text":       "#1e201c",
            "text_muted": "#82847f",
            "button":     "#f0d8a0",
            "primary":    "#c47c00",
            "secondary":  "#8a9300",
            "text_on_color": "#2a1500",
            "border":     "#dfe2dc",
            "good":       "#505a00",   # 6.5:1 on card
            "bad":        "#b02010",   # 5.9:1 on card
        },
        "dark": {
            "bg":         "#060705",
            "card":       "#191b17",
            "card2":      "#272925",
            "text":       "#f3f6f0",
            "text_muted": "#dfe2dc",
            "button":     "#3a3300",
            "primary":    "#ffcf8e",
            "secondary":  "#ddea63",
            "text_on_color": "#281600",
            "border":     "#595b56",
            "good":       "#ffe060",   # 13.3:1 on card
            "bad":        "#ff8060",   # 7.0:1 on card
        },
    },
}

THEME_NAMES = list(_THEMES.keys())


# Font size presets (pt)
FONT_SIZES = {"Small": 9, "Normal": 11, "Large": 13, "X-Large": 16}
FONT_SIZE_LABELS = list(FONT_SIZES.keys())


_UI = {
    "panel_radius": 14,
    "card_radius": 12,
    "group_radius": 10,
    "control_radius": 8,
    "title_radius": 7,
    "splitter_radius": 6,
    "cell_hpad": 10,
    "cell_vpad": 6,
    "header_hpad": 10,
    "header_vpad": 8,
    "control_hpad": 10,
    "control_vpad": 5,
    "button_hpad": 12,
    "button_vpad": 8,
}


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
    except Exception:
        return False


class ChevronProxyStyle(QProxyStyle):
    """Draw clearer chevrons for Qt arrow indicators across the app."""

    _ARROW_DIRECTIONS = {
        QStyle.PrimitiveElement.PE_IndicatorArrowDown: "down",
        QStyle.PrimitiveElement.PE_IndicatorArrowUp: "up",
        QStyle.PrimitiveElement.PE_IndicatorArrowLeft: "left",
        QStyle.PrimitiveElement.PE_IndicatorArrowRight: "right",
    }

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
    override_mode: str = "System"       # Colour Mode: System / Light / Dark
    match_system_accent: bool = True
    theme_name: str = "Default"         # Theme: Default / Warm Earth / Forest / etc.
    font_size_label: str = "Normal"     # Font Size: Small / Normal / Large / X-Large

    def __init__(self, window, poll_secs: int = 3):
        super().__init__(window)
        self.win = window
        self.poll_secs = poll_secs
        self._last_state = None
        self._timer: Optional[QTimer] = None
        self._chevron_style: Optional[ChevronProxyStyle] = None
        self._fixed_light_accent = (10, 102, 194)
        self._fixed_dark_accent  = (96, 165, 250)

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
        except Exception:
            return False

    def _windows_accent_rgb(self) -> Tuple[int, int, int]:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent") as k:
                v, _ = winreg.QueryValueEx(k, "AccentColor")
                return (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
        except Exception: pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
                v, _ = winreg.QueryValueEx(k, "ColorizationColor")
                return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
        except Exception: pass
        try:
            color = ctypes.c_uint(); opaque = ctypes.c_int()
            if ctypes.windll.dwmapi.DwmGetColorizationColor(ctypes.byref(color), ctypes.byref(opaque)) == 0:
                v = color.value
                return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
        except Exception: pass
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

    def _apply_font(self):
        pt = FONT_SIZES.get(self.font_size_label, 11)
        app = QApplication.instance()
        if app is not None:
            f = app.font()
            f.setPointSize(pt)
            app.setFont(f)

    def _is_light(self) -> bool:
        if self.override_mode in ("Light", "Dark"):
            return self.override_mode == "Light"
        if sys.platform.startswith("win"):
            return self._windows_is_light()
        return False

    def current_state(self) -> tuple:
        is_light = self._is_light()
        r, g, b = self._accent_for_mode(is_light)
        return (is_light, r, g, b, self.match_system_accent, self.theme_name, self.font_size_label)

    def start_watching(self):
        if self._timer is None:
            self._timer = QTimer(self.win)
            self._timer.setInterval(self.poll_secs * 1000)
            self._timer.timeout.connect(self._maybe_update_theme)
            self._timer.start()

    def _maybe_update_theme(self):
        if self.current_state() != self._last_state:
            self.apply()

    def apply(self):
        if sys.platform.startswith("win") and _windows_high_contrast_enabled():
            self.win.setStyleSheet("")
            for refresh_name in ("update_ui", "updateUI"):
                refresh = getattr(self.win, refresh_name, None)
                if callable(refresh):
                    try:
                        refresh()
                    except Exception:
                        pass
                    break
            return

        is_light, r, g, b, msa, tn, fsl = self.current_state()
        self._last_state = (is_light, r, g, b, msa, tn, fsl)

        theme_data = _THEMES.get(tn)
        if theme_data is None:
            accent = QColor(r, g, b)
            palette    = self._default_light_palette(accent) if is_light else self._default_dark_palette(accent)
            stylesheet = self._default_light_stylesheet(accent) if is_light else self._default_dark_stylesheet(accent)
        else:
            tokens  = theme_data["light" if is_light else "dark"]
            palette = self._themed_palette(tokens)
            stylesheet = self._themed_stylesheet(tokens)

        app = QApplication.instance()
        if app is not None:
            if self._chevron_style is None:
                existing_style = app.style()
                self._chevron_style = existing_style if isinstance(existing_style, ChevronProxyStyle) else ChevronProxyStyle(existing_style)
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
        except Exception:
            pass
        for refresh_name in ("update_ui", "updateUI"):
            refresh = getattr(self.win, refresh_name, None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass
                break
        self.win.update()
        self._apply_font()

    # ---- Colour accessor methods used by portfolio_tab / main_window ----

    def _tokens(self) -> Optional[dict]:
        """Return active theme tokens, or None for Default theme."""
        td = _THEMES.get(self.theme_name)
        if td is None:
            return None
        return td["light" if self._is_light() else "dark"]

    def profit_color(self) -> str:
        """Hex color for positive P/L text in tables — contrasts with card background."""
        t = self._tokens()
        if t:
            return t["good"]
        return "#4a9a30" if self._is_light() else "#6ee78a"

    def text_color(self) -> str:
        t = self._tokens()
        if t:
            return t["text"]
        return "#0f1115" if self._is_light() else "#eaeef2"

    def border_color(self) -> str:
        t = self._tokens()
        if t:
            return t["border"]
        return "#e5e7eb" if self._is_light() else "#232833"

    def button_color(self) -> str:
        t = self._tokens()
        if t:
            return t["button"]
        return "#ffffff" if self._is_light() else "#1f2430"

    def selected_surface_color(self) -> str:
        t = self._tokens()
        if t:
            return t["primary"]
        return "#f5f7fb" if self._is_light() else "#1f2430"

    def selected_text_color(self) -> str:
        t = self._tokens()
        if t:
            return t["text_on_color"]
        return "#0f1115" if self._is_light() else "#eaeef2"

    def focus_border_color(self) -> str:
        t = self._tokens()
        if t:
            return t["secondary"]
        is_light, r, g, b, *_ = self.current_state()
        return QColor(r, g, b).name()

    def loss_color(self) -> str:
        """Hex color for negative P/L text in tables — contrasts with card background."""
        t = self._tokens()
        if t:
            return t["bad"]
        return "#cc2222" if self._is_light() else "#f87171"

    def waiting_row_tint(self) -> Tuple[int, int, int, int]:
        """RGBA tint for WAITING/Pending order rows."""
        # Amber tint — slightly lighter in light themes
        return (160, 110, 10, 55) if self._is_light() else (180, 130, 0, 75)

    def short_row_tint(self) -> Tuple[int, int, int, int]:
        """RGBA tint for SHORT position rows."""
        return (20, 80, 180, 45) if self._is_light() else (40, 100, 210, 65)

    # ---- Named-theme builders ----

    def _themed_palette(self, t: dict) -> QPalette:
        p = QPalette()
        p.setColor(QPalette.Window,          QColor(t["bg"]))
        p.setColor(QPalette.Base,            QColor(t["card"]))
        p.setColor(QPalette.AlternateBase,   QColor(t["card2"]))
        p.setColor(QPalette.ToolTipBase,     QColor(t["card"]))
        p.setColor(QPalette.ToolTipText,     QColor(t["text"]))
        p.setColor(QPalette.Text,            QColor(t["text"]))
        p.setColor(QPalette.Button,          QColor(t["button"]))
        p.setColor(QPalette.ButtonText,      QColor(t["text"]))
        p.setColor(QPalette.Highlight,       QColor(t["secondary"]))
        p.setColor(QPalette.HighlightedText, QColor(t["text_on_color"]))
        p.setColor(QPalette.WindowText,      QColor(t["text"]))
        p.setColor(QPalette.PlaceholderText, QColor(t["text_muted"]))
        return p

    def _themed_stylesheet(self, t: dict) -> str:
        bg=t["bg"]; card=t["card"]; card2=t["card2"]; text=t["text"]
        muted=t["text_muted"]; btn=t["button"]; pri=t["primary"]
        sec=t["secondary"]; brd=t["border"]; toc=t["text_on_color"]
        panel_radius = _UI["panel_radius"]
        card_radius = _UI["card_radius"]
        group_radius = _UI["group_radius"]
        control_radius = _UI["control_radius"]
        title_radius = _UI["title_radius"]
        splitter_radius = _UI["splitter_radius"]
        cell_hpad = _UI["cell_hpad"]
        cell_vpad = _UI["cell_vpad"]
        header_hpad = _UI["header_hpad"]
        header_vpad = _UI["header_vpad"]
        control_hpad = _UI["control_hpad"]
        control_vpad = _UI["control_vpad"]
        button_hpad = _UI["button_hpad"]
        button_vpad = _UI["button_vpad"]
        chevron_down = self._chevron_asset("down")
        chevron_up = self._chevron_asset("up")
        return f"""
        QMainWindow {{ background: {bg}; color: {text}; }}
        QWidget {{ background: {card}; color: {text}; }}
        #leftPane {{ background: {bg}; border: 1px solid {brd}; border-radius: {panel_radius}px; }}
        #leftTitle {{ color: {muted}; font-size: 14px; font-weight: 700; padding: 4px 2px; }}
        #watchTableCard {{ background: {card}; border: 1px solid {brd}; border-radius: {card_radius}px; }}
        #watchTable {{ background: transparent; border: none; border-radius: {card_radius}px;
                       alternate-background-color: {card2};
                       selection-background-color: {sec}; selection-color: {toc}; }}
        #watchTable::item {{ padding: {cell_vpad}px {cell_hpad}px; border-bottom: 1px solid {brd}; }}
        #watchTable::item:selected {{ background: {sec}; color: {toc}; }}
        #watchTable QHeaderView {{ background: transparent; border: none; }}
        #watchTable QHeaderView::section {{ background: {card2}; color: {muted};
                                           border: none; border-bottom: 1px solid {brd};
                                           padding: {header_vpad}px {header_hpad}px; font-weight: 700; }}
        #watchTable QHeaderView::section:first {{ border-top-left-radius: {card_radius}px; }}
        #watchTable QHeaderView::section:last {{ border-top-right-radius: {card_radius}px; }}
        QToolTip {{ color: {text}; background: {card}; border: 1px solid {brd}; }}
        QDialog {{ background: {bg}; }}
        QScrollArea {{ background: {bg}; border: none; }}
        QScrollArea > QWidget > QWidget {{ background: {bg}; }}
        QLineEdit {{ background: {card}; border: 1px solid {brd}; border-radius: {control_radius}px;
                     padding: {control_vpad}px {control_hpad}px; min-height: 22px; color: {text}; }}
        QLineEdit:focus {{ border: 1px solid {sec}; }}
        QPushButton {{ background: {btn}; border: 1px solid {brd}; color: {text};
                       border-radius: {control_radius}px; padding: {button_vpad}px {button_hpad}px; font-weight: 600; }}
        QPushButton:hover {{ background: {pri}; }}
        QPushButton:pressed {{ background: {sec}; color: {toc}; }}
        QPushButton:focus {{ outline: none; border: 1px solid {sec}; }}
        QPushButton[flat="true"] {{ background: transparent; border: none; color: {muted}; }}
        QTabBar::tab {{ background: {card}; color: {text}; padding: 8px 14px;
                        border: 1px solid {brd};
                        border-top-left-radius: {control_radius}px; border-top-right-radius: {control_radius}px;
                        margin-right: 6px; margin-top: 0px; }}
        QTabBar::tab:selected {{ background: {pri}; color: {toc}; border-color: {sec}; margin-bottom: -1px; }}
        QTabWidget::pane {{ border: 1px solid {brd}; border-radius: {card_radius}px;
                            margin-top: 0px; top: -1px; background: {bg}; }}
        QGroupBox {{ border: 1px solid {brd}; border-radius: {group_radius}px; margin-top: 16px;
                     background: {card}; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 2px 8px;
                            color: {muted}; background: {card};
                            border: 1px solid {brd}; border-radius: {title_radius}px; }}
        QTableWidget {{ background: {card}; gridline-color: {brd}; color: {text};
                        alternate-background-color: {card2}; border: 1px solid {brd};
                        border-radius: {control_radius}px; }}
        QHeaderView::section {{ background: {card2}; color: {text}; border: 0px; padding: {cell_vpad}px {cell_hpad}px; }}
        QTableCornerButton::section {{ background: {card2}; border: 0px; border-top-left-radius: {control_radius}px; }}
        QTableWidget::item:selected {{ background: {sec}; color: {toc}; }}
        QComboBox {{ background: {card}; color: {text}; border: 1px solid {brd};
                     border-radius: {control_radius}px; padding: {control_vpad}px 34px {control_vpad}px {control_hpad}px; min-height: 22px; }}
        QComboBox:focus {{ border: 1px solid {sec}; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 26px; background: {card2}; border-left: 1px solid {brd};
            border-top-right-radius: {control_radius}px; border-bottom-right-radius: {control_radius}px;
        }}
        QComboBox::drop-down:hover {{ background: {btn}; }}
        QComboBox::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
        QComboBox QAbstractItemView {{ background: {card}; color: {text};
            selection-background-color: {sec}; selection-color: {toc};
            border: 1px solid {brd}; }}
        QSpinBox, QDoubleSpinBox {{ background: {card}; color: {text}; border: 1px solid {brd};
                                    border-radius: {control_radius}px; padding: {control_vpad}px 32px {control_vpad}px {control_hpad}px; min-height: 22px; }}
        QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {sec}; }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border; subcontrol-position: top right;
            width: 22px; background: {card2}; border-left: 1px solid {brd};
            border-bottom: 1px solid {brd}; border-top-right-radius: {control_radius}px;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border; subcontrol-position: bottom right;
            width: 22px; background: {card2}; border-left: 1px solid {brd};
            border-bottom-right-radius: {control_radius}px;
        }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {btn}; }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url("{chevron_up}"); width: 12px; height: 12px;
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url("{chevron_down}"); width: 12px; height: 12px;
        }}
        QDateEdit {{ background: {card}; color: {text}; border: 1px solid {brd};
                     border-radius: {control_radius}px; padding: {control_vpad}px 34px {control_vpad}px {control_hpad}px; min-height: 22px; }}
        QDateEdit:focus {{ border: 1px solid {sec}; }}
        QDateEdit::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 26px; background: {card2}; border-left: 1px solid {brd};
            border-top-right-radius: {control_radius}px; border-bottom-right-radius: {control_radius}px;
        }}
        QDateEdit::drop-down:hover {{ background: {btn}; }}
        QDateEdit::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
        QCheckBox {{ color: {text}; spacing: 6px; }}
        QCheckBox::indicator {{ border: 1px solid {brd}; border-radius: 4px;
                                background: {card}; width: 14px; height: 14px; }}
        QCheckBox::indicator:checked {{ background: {sec}; border-color: {sec}; }}
        QMenu {{ background: {card}; color: {text}; border: 1px solid {brd}; }}
        QMenu::item {{ padding: 6px 18px 6px 18px; }}
        QMenu::item:selected {{ background: {sec}; color: {toc}; }}
        QMenu::separator {{ height: 1px; background: {brd}; margin: 4px 6px; }}
        QProgressBar {{ background: {card}; border: 1px solid {brd}; border-radius: {control_radius}px;
                        text-align: center; color: {text}; }}
        QProgressBar::chunk {{ background-color: {sec}; border-radius: {control_radius}px; }}
        QScrollBar:vertical {{ background: {bg}; width: 8px; border-radius: 4px; }}
        QScrollBar::handle:vertical {{ background: {brd}; border-radius: 4px; min-height: 20px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QSplitter::handle {{ background: {brd}; border-radius: {splitter_radius}px; margin: 4px 2px; }}
        QStatusBar {{ background: {bg}; color: {muted}; }}
        QMenuBar {{ background: {bg}; color: {text}; border-bottom: 1px solid {brd}; padding-bottom: 2px; }}
        QMenuBar::item:selected {{ background: {pri}; color: {toc}; }}
        #menuStatusCorner {{ background: {bg}; border: none; }}
        #menuStatusCorner QLabel {{ background: transparent; padding: 0px; border: none; text-decoration: none; }}
        QLabel {{ color: {text}; background: transparent; }}
        """

    # ---- Default theme builders (original, unchanged) ----

    def _default_dark_palette(self, accent: QColor) -> QPalette:
        p = QPalette()
        p.setColor(QPalette.Window,          QColor("#0f1115"))
        p.setColor(QPalette.Base,            QColor("#14171d"))
        p.setColor(QPalette.AlternateBase,   QColor("#171a21"))
        p.setColor(QPalette.ToolTipBase,     QColor("#10131a"))
        p.setColor(QPalette.ToolTipText,     QColor("#eaeef2"))
        p.setColor(QPalette.Text,            QColor("#eaeef2"))
        p.setColor(QPalette.Button,          QColor("#1f2430"))
        p.setColor(QPalette.ButtonText,      QColor("#eaeef2"))
        p.setColor(QPalette.Highlight,       accent)
        p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        p.setColor(QPalette.WindowText,      QColor("#eaeef2"))
        p.setColor(QPalette.PlaceholderText, QColor("#a9b1bd"))
        return p

    def _default_light_palette(self, accent: QColor) -> QPalette:
        p = QPalette()
        p.setColor(QPalette.Window,          QColor("#ffffff"))
        p.setColor(QPalette.Base,            QColor("#f8fafc"))
        p.setColor(QPalette.AlternateBase,   QColor("#eef2f7"))
        p.setColor(QPalette.ToolTipBase,     QColor("#f3f5f7"))
        p.setColor(QPalette.ToolTipText,     QColor("#0f1115"))
        p.setColor(QPalette.Text,            QColor("#0f1115"))
        p.setColor(QPalette.Button,          QColor("#ffffff"))
        p.setColor(QPalette.ButtonText,      QColor("#0f1115"))
        p.setColor(QPalette.Highlight,       accent)
        p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        p.setColor(QPalette.WindowText,      QColor("#0f1115"))
        p.setColor(QPalette.PlaceholderText, QColor("#4b5563"))
        return p

    def _default_dark_stylesheet(self, accent: QColor) -> str:
        acc = accent.name()
        chevron_down = self._chevron_asset("down")
        chevron_up = self._chevron_asset("up")
        return f"""
        QMainWindow {{ background: #0f1115; color: #eaeef2; }}
        #leftPane {{ background: #0f1115; border: 1px solid #232833; border-radius: 14px; }}
        #leftTitle {{ color: #a9b1bd; font-size: 14px; font-weight: 700; padding: 4px 2px; }}
        #watchTableCard {{ background: #10131a; border: 1px solid #232833; border-radius: 12px; }}
        #watchTable {{ background: transparent; border: none; border-radius: 12px;
                       alternate-background-color: #14171d;
                       selection-background-color: {acc}; selection-color: white; }}
        #watchTable::item {{ padding: 6px 8px; border-bottom: 1px solid #232833; }}
        #watchTable::item:selected {{ background: {acc}; color: white; }}
        #watchTable QHeaderView {{ background: transparent; border: none; }}
        #watchTable QHeaderView::section {{ background: #171a21; color: #a9b1bd;
                                           border: none; border-bottom: 1px solid #232833;
                                           padding: 8px 10px; font-weight: 700; }}
        #watchTable QHeaderView::section:first {{ border-top-left-radius: 12px; }}
        #watchTable QHeaderView::section:last {{ border-top-right-radius: 12px; }}
        QToolTip {{ color: #eaeef2; background: #10131a; border: 1px solid #232833; }}
        QLineEdit {{ background: #171a21; border: 1px solid #232833; border-radius: 8px;
                     padding: 5px 10px; min-height: 22px; color: #eaeef2; }}
        QLineEdit:focus {{ border: 1px solid {acc}; }}
        QPushButton {{ background: #1f2430; border: 1px solid #2b3240; color: #eaeef2;
                       border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
        QPushButton:hover {{ background: #262d3a; }}
        QPushButton:pressed {{ background: #2b3240; }}
        QPushButton:focus {{ outline: none; border: 1px solid {acc}; }}
        QTabBar::tab {{ background: #171a21; color: #eaeef2; padding: 8px 14px;
                        border: 1px solid #232833;
                        border-top-left-radius: 8px; border-top-right-radius: 8px;
                        margin-right: 6px; margin-top: 0px; }}
        QTabBar::tab:selected {{ background: #1f2430; border-color: {acc}; margin-bottom: -1px; }}
        QTabWidget::pane {{ border: 1px solid #232833; border-radius: 12px;
                            margin-top: 0px; top: -1px; background: #0f1115; }}
        QGroupBox {{ border: 1px solid #232833; border-radius: 10px; margin-top: 16px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 2px 8px;
                            color: #a9b1bd; background: #171a21;
                            border: 1px solid #232833; border-radius: 7px; }}
        QTableWidget {{ background: #0f1115; gridline-color: #232833; color: #eaeef2;
                        alternate-background-color: #14171d; border: 1px solid #232833;
                        border-radius: 8px; }}
        QHeaderView::section {{ background: #171a21; color: #eaeef2; border: 0px; padding: 6px; }}
        QTableCornerButton::section {{ background: #171a21; border: 0px; border-top-left-radius: 8px; }}
        QTableWidget::item:selected {{ background: {acc}; color: white; }}
        QComboBox {{ background: #171a21; color: #eaeef2; border: 1px solid #232833;
                     border-radius: 8px; padding: 5px 34px 5px 10px; min-height: 22px; }}
        QComboBox:focus {{ border: 1px solid {acc}; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 26px; background: #1f2430; border-left: 1px solid #232833;
            border-top-right-radius: 8px; border-bottom-right-radius: 8px;
        }}
        QComboBox::drop-down:hover {{ background: #262d3a; }}
        QComboBox::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
        QComboBox QAbstractItemView {{ background: #171a21; color: #eaeef2;
            selection-background-color: {acc}; selection-color: white;
            border: 1px solid #232833; }}
        QSpinBox, QDoubleSpinBox {{ background: #171a21; color: #eaeef2; border: 1px solid #232833;
                                    border-radius: 8px; padding: 5px 32px 5px 10px; min-height: 22px; }}
        QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {acc}; }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border; subcontrol-position: top right;
            width: 22px; background: #1f2430; border-left: 1px solid #232833;
            border-bottom: 1px solid #232833; border-top-right-radius: 8px;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border; subcontrol-position: bottom right;
            width: 22px; background: #1f2430; border-left: 1px solid #232833;
            border-bottom-right-radius: 8px;
        }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #262d3a; }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url("{chevron_up}"); width: 12px; height: 12px;
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url("{chevron_down}"); width: 12px; height: 12px;
        }}
        QDateEdit {{ background: #171a21; color: #eaeef2; border: 1px solid #232833;
                     border-radius: 8px; padding: 5px 34px 5px 10px; min-height: 22px; }}
        QDateEdit:focus {{ border: 1px solid {acc}; }}
        QDateEdit::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 26px; background: #1f2430; border-left: 1px solid #232833;
            border-top-right-radius: 8px; border-bottom-right-radius: 8px;
        }}
        QDateEdit::drop-down:hover {{ background: #262d3a; }}
        QDateEdit::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
        QMenu {{ background: #171a21; color: #eaeef2; border: 1px solid #232833; }}
        QMenu::item {{ padding: 6px 18px 6px 18px; }}
        QMenu::item:selected {{ background: {acc}; color: white; }}
        QMenu::separator {{ height: 1px; background: #232833; margin: 4px 6px; }}
        QProgressBar {{ background: #171a21; border: 1px solid #232833; border-radius: 8px;
                        text-align: center; color: #eaeef2; }}
        QProgressBar::chunk {{ background-color: {acc}; border-radius: 8px; }}
        QSplitter::handle {{ background: #232833; border-radius: 6px; margin: 4px 2px; }}
        QMenuBar {{ background: #0f1115; color: #eaeef2; border-bottom: 1px solid #232833; padding-bottom: 2px; }}
        QMenuBar::item:selected {{ background: #1f2430; color: #eaeef2; }}
        #menuStatusCorner {{ background: #0f1115; border: none; }}
        #menuStatusCorner QLabel {{ background: transparent; padding: 0px; border: none; text-decoration: none; }}
        """

    def _default_light_stylesheet(self, accent: QColor) -> str:
        acc = accent.name()
        chevron_down = self._chevron_asset("down")
        chevron_up = self._chevron_asset("up")
        return f"""
        QMainWindow {{ background: #ffffff; color: #0f1115; }}
        #leftPane {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 14px; }}
        #leftTitle {{ color: #374151; font-size: 14px; font-weight: 700; padding: 4px 2px; }}
        #watchTableCard {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; }}
        #watchTable {{ background: transparent; border: none; border-radius: 12px;
                       alternate-background-color: #f8fafc;
                       selection-background-color: {acc}; selection-color: white; }}
        #watchTable::item {{ padding: 6px 8px; border-bottom: 1px solid #e5e7eb; }}
        #watchTable::item:selected {{ background: {acc}; color: white; }}
        #watchTable QHeaderView {{ background: transparent; border: none; }}
        #watchTable QHeaderView::section {{ background: #f3f4f6; color: #374151;
                                           border: none; border-bottom: 1px solid #e5e7eb;
                                           padding: 8px 10px; font-weight: 700; }}
        #watchTable QHeaderView::section:first {{ border-top-left-radius: 12px; }}
        #watchTable QHeaderView::section:last {{ border-top-right-radius: 12px; }}
        QToolTip {{ color: #0f1115; background: #f3f5f7; border: 1px solid #e5e7eb; }}
        QLineEdit {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
                     padding: 5px 10px; min-height: 22px; color: #0f1115; }}
        QLineEdit:focus {{ border: 1px solid {acc}; }}
        QPushButton {{ background: #ffffff; border: 1px solid #e5e7eb; color: #0f1115;
                       border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
        QPushButton:hover {{ background: #f5f7fb; }}
        QPushButton:pressed {{ background: #eef2f7; }}
        QPushButton:focus {{ outline: none; border: 1px solid {acc}; }}
        QTabBar::tab {{ background: #ffffff; color: #0f1115; padding: 8px 14px;
                        border: 1px solid #e5e7eb;
                        border-top-left-radius: 8px; border-top-right-radius: 8px;
                        margin-right: 6px; margin-top: 0px; }}
        QTabBar::tab:selected {{ background: #f5f7fb; border-color: {acc}; margin-bottom: -1px; }}
        QTabWidget::pane {{ border: 1px solid #e5e7eb; border-radius: 12px;
                            margin-top: 0px; top: -1px; background: #ffffff; }}
        QGroupBox {{ border: 1px solid #e5e7eb; border-radius: 10px; margin-top: 16px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 2px 8px;
                            color: #374151; background: #ffffff;
                            border: 1px solid #e5e7eb; border-radius: 7px; }}
        QTableWidget {{ background: #ffffff; gridline-color: #e5e7eb; color: #0f1115;
                        alternate-background-color: #f8fafc; border: 1px solid #e5e7eb;
                        border-radius: 8px; }}
        QHeaderView::section {{ background: #f3f4f6; color: #0f1115; border: 0px; padding: 6px; }}
        QTableCornerButton::section {{ background: #f3f4f6; border: 0px; border-top-left-radius: 8px; }}
        QTableWidget::item:selected {{ background: {acc}; color: white; }}
        QComboBox {{ background: #ffffff; color: #0f1115; border: 1px solid #e5e7eb;
                     border-radius: 8px; padding: 5px 34px 5px 10px; min-height: 22px; }}
        QComboBox:focus {{ border: 1px solid {acc}; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 26px; background: #f3f4f6; border-left: 1px solid #e5e7eb;
            border-top-right-radius: 8px; border-bottom-right-radius: 8px;
        }}
        QComboBox::drop-down:hover {{ background: #eef2f7; }}
        QComboBox::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
        QComboBox QAbstractItemView {{ background: #ffffff; color: #0f1115;
            selection-background-color: {acc}; selection-color: white;
            border: 1px solid #e5e7eb; }}
        QSpinBox, QDoubleSpinBox {{ background: #ffffff; color: #0f1115; border: 1px solid #e5e7eb;
                                    border-radius: 8px; padding: 5px 32px 5px 10px; min-height: 22px; }}
        QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {acc}; }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border; subcontrol-position: top right;
            width: 22px; background: #f3f4f6; border-left: 1px solid #e5e7eb;
            border-bottom: 1px solid #e5e7eb; border-top-right-radius: 8px;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border; subcontrol-position: bottom right;
            width: 22px; background: #f3f4f6; border-left: 1px solid #e5e7eb;
            border-bottom-right-radius: 8px;
        }}
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #eef2f7; }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url("{chevron_up}"); width: 12px; height: 12px;
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url("{chevron_down}"); width: 12px; height: 12px;
        }}
        QDateEdit {{ background: #ffffff; color: #0f1115; border: 1px solid #e5e7eb;
                     border-radius: 8px; padding: 5px 34px 5px 10px; min-height: 22px; }}
        QDateEdit:focus {{ border: 1px solid {acc}; }}
        QDateEdit::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 26px; background: #f3f4f6; border-left: 1px solid #e5e7eb;
            border-top-right-radius: 8px; border-bottom-right-radius: 8px;
        }}
        QDateEdit::drop-down:hover {{ background: #eef2f7; }}
        QDateEdit::down-arrow {{ image: url("{chevron_down}"); width: 12px; height: 12px; }}
        QMenu {{ background: #ffffff; color: #0f1115; border: 1px solid #e5e7eb; }}
        QMenu::item {{ padding: 6px 18px 6px 18px; }}
        QMenu::item:selected {{ background: {acc}; color: white; }}
        QMenu::separator {{ height: 1px; background: #e5e7eb; margin: 4px 6px; }}
        QProgressBar {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
                        text-align: center; color: #0f1115; }}
        QProgressBar::chunk {{ background-color: {acc}; border-radius: 8px; }}
        QSplitter::handle {{ background: #e5e7eb; border-radius: 6px; margin: 4px 2px; }}
        QMenuBar {{ background: #ffffff; color: #0f1115; border-bottom: 1px solid #e5e7eb; padding-bottom: 2px; }}
        QMenuBar::item:selected {{ background: #eef2f7; color: #0f1115; }}
        #menuStatusCorner {{ background: #ffffff; border: none; }}
        #menuStatusCorner QLabel {{ background: transparent; padding: 0px; border: none; text-decoration: none; }}
        """

    # Aliases for old call sites
    _dark_palette      = _default_dark_palette
    _light_palette     = _default_light_palette
    _dark_stylesheet   = _default_dark_stylesheet
    _light_stylesheet  = _default_light_stylesheet
