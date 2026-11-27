"""The manager's look: Harbor tokens, fonts and one stylesheet.

Its own small copy of the Harbor palette (``docs/design/design-system.md``) so the
manager does not import ``stock_insights.theme`` and with it the desktop app.
Keep the shared token values in step with ``stock_insights/theme.py``.

One token is added for this app only: ``warn``, the colour of a "wants a look"
state mark and the tint behind warning lines in the server output. Harbor's
amber ``pace`` stays reserved for the pace rail, so ``warn`` is a darker,
text-safe amber of its own. Every state also has a shape and a word; colour is
never the only signal.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

HARBOR = {
    "light": {
        "bg": "#E8ECEF", "card": "#F8FAFB", "card2": "#EEF2F5", "text": "#15202B",
        "text_muted": "#566472", "border": "#D3DAE0", "primary": "#2C55C9",
        "text_on_color": "#FFFFFF", "good": "#0B7A5C", "bad": "#B83A2E",
        "warn": "#8F5B00", "warn_tint": "#FBEFD9", "bad_tint": "#FBE7E4",
    },
    "dark": {
        "bg": "#161D24", "card": "#1F2830", "card2": "#27323C", "text": "#E4EAF0",
        "text_muted": "#93A2B0", "border": "#33404B", "primary": "#7FA2FF",
        "text_on_color": "#0E1620", "good": "#4CC9A0", "bad": "#FF7B6B",
        "warn": "#E9B04A", "warn_tint": "#3A3122", "bad_tint": "#3D2626",
    },
}

RADIUS_PANEL = 10
RADIUS_CONTROL = 6

_mode = "light"
_fonts = {"text": "", "display": "", "mono": ""}


def mode() -> str:
    return _mode


def c(token: str) -> str:
    return HARBOR[_mode][token]


def qc(token: str, alpha: int | None = None) -> QColor:
    col = QColor(c(token))
    if alpha is not None:
        col.setAlpha(alpha)
    return col


def tone_color(tone: str) -> str:
    return c({"good": "good", "warn": "warn", "bad": "bad", "busy": "primary"}.get(tone, "text_muted"))


def font(size_px: int = 13, weight: int = 400, display: bool = False) -> QFont:
    f = QFont(_fonts["display" if display else "text"] or QApplication.font().family())
    f.setPixelSize(size_px)
    f.setWeight(QFont.Weight(weight))
    return f


def mono_font(size_px: int = 12) -> QFont:
    f = QFont(_fonts["mono"])
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(size_px)
    return f


def _pick(candidates: tuple[str, ...], fallback: str) -> str:
    installed = set(QFontDatabase.families())
    return next((f for f in candidates if f in installed), fallback)


def _detect_mode() -> str:
    forced = os.environ.get("SI_MANAGER_THEME", "").lower()
    if forced in ("light", "dark"):
        return forced
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        return "dark" if scheme == Qt.ColorScheme.Dark else "light"
    except AttributeError:      # Qt older than 6.5
        return "light"


def apply(app: QApplication) -> None:
    """Resolve fonts, pick light/dark, install the palette and stylesheet."""
    global _mode
    _mode = _detect_mode()
    general = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    _fonts["text"] = _pick(("Segoe UI Variable Text", "Segoe UI"), general)
    _fonts["display"] = _pick(("Segoe UI Variable Display", "Segoe UI"), general)
    fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    _fonts["mono"] = _pick(("Cascadia Mono", "Consolas"), fixed)
    app.setFont(font(13))

    pal = QPalette()
    for role, token in ((QPalette.Window, "bg"), (QPalette.Base, "card"),
                        (QPalette.AlternateBase, "card2"), (QPalette.Button, "card2"),
                        (QPalette.WindowText, "text"), (QPalette.Text, "text"),
                        (QPalette.ButtonText, "text"), (QPalette.Highlight, "primary"),
                        (QPalette.HighlightedText, "text_on_color"),
                        (QPalette.PlaceholderText, "text_muted"), (QPalette.ToolTipBase, "card"),
                        (QPalette.ToolTipText, "text")):
        pal.setColor(role, qc(token))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    t = HARBOR[_mode]
    return f"""
    QMainWindow, QWidget#page {{ background: {t['bg']}; }}
    QWidget {{ color: {t['text']}; }}
    QFrame#panel {{ background: {t['card']}; border-radius: {RADIUS_PANEL}px; }}
    QLabel#muted {{ color: {t['text_muted']}; }}
    QLabel#panelTitle {{ font-size: 15px; font-weight: 600; }}
    QLabel#pageTitle {{ font-size: 20px; font-weight: 600; }}
    QListWidget#nav {{ background: {t['bg']}; border: none; outline: none; font-size: 13px; }}
    QListWidget#nav::item {{ min-height: 36px; padding: 0 12px; border-radius: {RADIUS_CONTROL}px;
                             margin: 1px 8px; color: {t['text']}; }}
    QListWidget#nav::item:hover {{ background: {t['card2']}; }}
    QListWidget#nav::item:selected {{ background: {t['card']}; color: {t['primary']};
                                      font-weight: 600; }}
    QListWidget#nav[focused="true"]::item:selected {{ border: 2px solid {t['primary']}; }}
    QPushButton {{ background: {t['card2']}; border: 1px solid {t['border']};
                   border-radius: {RADIUS_CONTROL}px; padding: 6px 14px; min-height: 20px; }}
    QPushButton:hover {{ border-color: {t['text_muted']}; }}
    QPushButton:focus {{ border: 2px solid {t['primary']}; padding: 5px 13px; }}
    QPushButton:checked {{ background: {t['card']}; border: 2px solid {t['primary']};
                           padding: 5px 13px; }}
    QPushButton:disabled {{ color: {t['text_muted']}; background: {t['card2']};
                            border-color: {t['card2']}; }}
    QPushButton#primary {{ background: {t['primary']}; color: {t['text_on_color']};
                           border: 1px solid {t['primary']}; font-weight: 600; }}
    QPushButton#primary:focus {{ border: 2px solid {t['text']}; }}
    QPushButton#danger {{ color: {t['bad']}; border: 1px solid {t['bad']}; background: {t['card']}; }}
    QPushButton#danger:focus {{ border: 2px solid {t['bad']}; }}
    QPushButton#danger:disabled {{ color: {t['text_muted']}; background: {t['card2']};
                                   border-color: {t['card2']}; }}
    QLineEdit, QPlainTextEdit {{ background: {t['card2']}; border: 1px solid {t['border']};
                 border-radius: {RADIUS_CONTROL}px; padding: 4px 8px;
                 selection-background-color: {t['primary']};
                 selection-color: {t['text_on_color']}; }}
    QLineEdit {{ min-height: 22px; }}
    QLineEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {t['primary']}; }}
    QPlainTextEdit#output {{ background: {t['card']}; border: none; padding: 8px 4px; }}
    QPlainTextEdit#command {{ background: {t['card2']}; border: none; padding: 6px 8px; }}
    QAbstractScrollArea::corner {{ background: transparent; border: none; }}
    QTableWidget {{ background: {t['card']}; border: none; gridline-color: {t['border']};
                    selection-background-color: {t['card2']}; selection-color: {t['text']}; }}
    QTableWidget::item {{ border-bottom: 1px solid {t['border']}; padding: 0 10px; }}
    QTableWidget:focus {{ border: 2px solid {t['primary']}; border-radius: {RADIUS_PANEL}px; }}
    QHeaderView::section {{ background: {t['card2']}; color: {t['text_muted']}; font-size: 12px;
                            font-weight: 600; border: none; padding: 8px 10px; }}
    QStatusBar {{ background: {t['bg']}; color: {t['text_muted']}; }}
    QStatusBar QLabel {{ color: {t['text_muted']}; padding: 0 8px; }}
    QStatusBar QLabel#stale {{ color: {t['bad']}; font-weight: 600; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 30px; }}
    QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']}; }}
    """
