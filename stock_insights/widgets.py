"""Shared building blocks for the QWidget windows and dialogs.

Everything here follows the Harbor design system (docs/design/design-system.md):
16 px panel padding, 12 px gaps, sentence-case copy, the primary action as the
default button on the right, and colours read from the active ThemeManager
(never literals) so all nine themes in light and dark work.

Contents
    SpinnerLabel        text spinner shown while background work runs
    find_theme_manager  locate the app's ThemeManager from any widget
    theme_color         one Harbor token (good, bad, text_muted, ...) as a QColor
    set_text_role       colour a QLabel by role (muted / good / bad / error) and
                        keep it in sync when the theme changes
    scaled_font         font at a Harbor type-scale step (12 / 13 / 15 / 20 / 28)
    dialog_layout       root QVBoxLayout with Harbor margins and spacing
    Panel               a titled card section that holds a form or other content
    make_form           QFormLayout with Harbor alignment + spacing
    align_form_labels   line up label columns across several forms
    add_dialog_buttons  Cancel + primary action button row
    confirm             yes/no question whose buttons name the action
    fmt_money / fmt_signed_money / fmt_int / fmt_status
                        number and status formatting shared by dialogs
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Harbor spacing (px).
PANEL_PADDING = 16
GAP = 12
FORM_ROW_GAP = 10

MINUS = "−"  # real minus sign for negative numbers (Harbor "Words")


class SpinnerLabel(QLabel):
    """Simple text spinner used while background work is running."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._index = 0

    def start(self, interval_ms: int = 80) -> None:
        self._index = 0
        self._timer.start(interval_ms)

    def stop(self) -> None:
        self._timer.stop()
        try:
            self.setText("")
        except RuntimeError:
            # C++ object already deleted — nothing to do.
            pass

    def _tick(self) -> None:
        try:
            self.setText(self.FRAMES[self._index % len(self.FRAMES)])
        except RuntimeError:
            self._timer.stop()
            return
        self._index += 1


# ---------------------------------------------------------------------------
# Theme access
# ---------------------------------------------------------------------------

def find_theme_manager(widget: Optional[QWidget] = None):
    """Return the ThemeManager that styles `widget`, or None.

    Search order: `.theme` on the widget or any ancestor (MainWindow owns one),
    then any top-level window with a `.theme`, then any ThemeManager parented
    to a top-level widget (main.py's startup theme uses a hidden dummy).
    """
    from .theme import ThemeManager

    w = widget
    while w is not None:
        tm = getattr(w, "theme", None)
        if isinstance(tm, ThemeManager):
            return tm
        w = w.parentWidget()
    app = QApplication.instance()
    if app is None:
        return None
    tops = app.topLevelWidgets()
    for top in tops:
        tm = getattr(top, "theme", None)
        if isinstance(tm, ThemeManager):
            return tm
    for top in tops:
        found = top.findChildren(ThemeManager)
        if found:
            return found[-1]
    return None


# Palette roles used when no ThemeManager is reachable (e.g. a bare test).
_PALETTE_FALLBACK = {
    "bg": QPalette.ColorRole.Window,
    "card": QPalette.ColorRole.Base,
    "card2": QPalette.ColorRole.AlternateBase,
    "text": QPalette.ColorRole.WindowText,
    "text_muted": QPalette.ColorRole.PlaceholderText,
    "border": QPalette.ColorRole.Mid,
    "primary": QPalette.ColorRole.Highlight,
    "text_on_color": QPalette.ColorRole.HighlightedText,
}
# Harbor good/bad for when there is no theme at all (light, dark).
_GAIN_LOSS_FALLBACK = {"good": ("#0B7A5C", "#4CC9A0"), "bad": ("#B83A2E", "#FF7B6B")}


def theme_color(token: str, widget: Optional[QWidget] = None) -> QColor:
    """Active colour for a Harbor token name (see theme.py `_THEMES`).

    `error` is an alias for `bad`. Falls back to the application palette (and
    Harbor's own gain/loss values) when no ThemeManager exists.
    """
    token = "bad" if token == "error" else token
    tm = find_theme_manager(widget)
    if tm is not None:
        tokens_fn = getattr(tm, "tokens", None)
        if callable(tokens_fn):
            value = tokens_fn().get(token)
            if value:
                return QColor(value)
        legacy = {"good": "profit_color", "bad": "loss_color", "text": "text_color",
                  "border": "border_color"}.get(token)
        if legacy and hasattr(tm, legacy):
            return QColor(getattr(tm, legacy)())
    palette = QApplication.palette() if QApplication.instance() else QPalette()
    if token in _GAIN_LOSS_FALLBACK:
        is_dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
        return QColor(_GAIN_LOSS_FALLBACK[token][1 if is_dark else 0])
    return palette.color(_PALETTE_FALLBACK.get(token, QPalette.ColorRole.WindowText))


def pl_role(value: Optional[float]) -> str:
    """Text role for a profit/loss number: good, bad or muted (zero / none)."""
    if value is None or abs(value) < 0.005:
        return "muted"
    return "good" if value > 0 else "bad"


class _RoleColorSync(QObject):
    """Re-colours a label whenever the app palette or stylesheet changes.

    The global QSS sets `QLabel { color: text }`, which beats QPalette, so the
    role colour has to be a per-widget `color:` rule. It is recomputed from
    the ThemeManager on every theme change, so no colour is ever hard-coded.
    """

    def __init__(self, label: QLabel):
        super().__init__(label)
        self._busy = False

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange) and not self._busy:
            self._busy = True
            try:
                _apply_role_color(obj)
            finally:
                self._busy = False
        return False


def _apply_role_color(label: QLabel) -> None:
    role = label.property("role") or ""
    token = {"muted": "text_muted", "good": "good", "bad": "bad", "error": "bad"}.get(role)
    sheet = f"color: {theme_color(token, label).name()};" if token else ""
    if label.styleSheet() != sheet:
        label.setStyleSheet(sheet)


def set_text_role(label: QLabel, role: str) -> QLabel:
    """Colour `label` by meaning: "muted", "good", "bad", "error" or "" (normal).

    Sets the dynamic property `role` (so the global QSS can style it too) and
    keeps the colour in sync with theme changes. Returns the label.
    """
    if label.property("role") == role and label.findChild(_RoleColorSync) is not None:
        return label
    label.setProperty("role", role)
    if label.findChild(_RoleColorSync) is None:
        label.installEventFilter(_RoleColorSync(label))
    _apply_role_color(label)
    return label


def muted_label(text: str = "", wrap: bool = True) -> QLabel:
    """Secondary text (help, captions) in `text_muted`."""
    lbl = QLabel(text)
    lbl.setWordWrap(wrap)
    return set_text_role(lbl, "muted")


# Harbor type scale in px at "Normal" (13 px body). Fonts are scaled relative
# to the app font so the user's font-size setting still applies.
_BODY_PX = 13.0


def scaled_font(base: QFont, px: float, weight: Optional[int] = None) -> QFont:
    """Copy of `base` resized to Harbor step `px` (12/13/15/20/28) and weight."""
    f = QFont(base)
    pt = base.pointSizeF() if base.pointSizeF() > 0 else 11.0
    f.setPointSizeF(pt * px / _BODY_PX)
    if weight is not None:
        f.setWeight(QFont.Weight(weight))
    return f


def heading_label(text: str, px: float = 15) -> QLabel:
    """Section / dialog heading: weight 600 at the given scale step."""
    lbl = QLabel(text)
    lbl.setFont(scaled_font(lbl.font(), px, 600))
    lbl.setProperty("role", "heading")
    return lbl


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def dialog_layout(dialog: QWidget) -> QVBoxLayout:
    """Root layout for a dialog: 16 px margins, 12 px between sections."""
    root = QVBoxLayout(dialog)
    root.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_PADDING)
    root.setSpacing(GAP)
    return root


def make_form(parent: Optional[QWidget] = None) -> QFormLayout:
    """Form with labels left-aligned in their own column, fields growing."""
    form = QFormLayout(parent) if parent is not None else QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(GAP)
    form.setVerticalSpacing(FORM_ROW_GAP)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    return form


def align_form_labels(*forms: QFormLayout) -> None:
    """Give every label in `forms` the same width so fields in stacked
    panels line up in one column. Call after all rows are added."""
    labels = []
    for form in forms:
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is not None and item.widget() is not None:
                labels.append(item.widget())
    if labels:
        width = max(lbl.sizeHint().width() for lbl in labels)
        for lbl in labels:
            lbl.setMinimumWidth(width)


class Panel(QFrame):
    """A Harbor "deck" panel: card surface, 16 px padding, optional heading.

    Put content in `panel.body` (a QVBoxLayout) or use `panel.form()` to get a
    ready-made form layout inside it. The surface comes from the global QSS
    (`QWidget { background: card }`); `role="panel"` lets the theme add the
    10 px radius.
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None, subtitle: str = ""):
        super().__init__(parent)
        self.setProperty("role", "panel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_PADDING)
        self.body.setSpacing(GAP)
        self.title_label: Optional[QLabel] = None
        if title:
            self.title_label = heading_label(title)
            self.body.addWidget(self.title_label)
        if subtitle:
            self.body.addWidget(muted_label(subtitle))
        self._form: Optional[QFormLayout] = None

    def form(self) -> QFormLayout:
        if self._form is None:
            self._form = make_form()
            self.body.addLayout(self._form)
        return self._form

    def setTitle(self, title: str) -> None:  # noqa: N802 (QGroupBox-compatible name)
        if self.title_label is not None:
            self.title_label.setText(title)


def add_dialog_buttons(
        dialog: QDialog,
        layout: QLayout,
        primary_text: Optional[str],
        on_primary: Optional[Callable[[], None]] = None,
        cancel_text: str = "Cancel",
        leading: Sequence[QWidget] = (),
) -> Tuple[QHBoxLayout, Optional[QPushButton]]:
    """Add the Harbor button row: [leading...]  ...  [Cancel] [Primary].

    The primary action sits on the right and is the default button (Enter
    triggers it; the global QSS gives `:default` the primary fill).
    `on_primary` defaults to `dialog.accept`. Pass `primary_text=None` for a
    read-only dialog that only needs a close button (`cancel_text` names it,
    e.g. "Close"). `leading` widgets (e.g. "Work offline") sit on the left.
    A plain row is used instead of QDialogButtonBox because the box reorders
    buttons per platform and Windows would put the primary on the left.
    """
    row = QHBoxLayout()
    row.setContentsMargins(0, 4, 0, 0)
    row.setSpacing(8)
    for w in leading:
        row.addWidget(w)
    row.addStretch(1)
    primary: Optional[QPushButton] = None
    if cancel_text:
        secondary = QPushButton(cancel_text)
        secondary.setAutoDefault(False)
        secondary.clicked.connect(dialog.reject)
        row.addWidget(secondary)
        if not primary_text:
            secondary.setDefault(True)
    if primary_text:
        primary = QPushButton(primary_text)
        primary.setDefault(True)
        primary.setAutoDefault(True)
        primary.setProperty("role", "primary")
        primary.clicked.connect(on_primary or dialog.accept)
        row.addWidget(primary)
    layout.addLayout(row)
    return row, primary


def confirm(parent: Optional[QWidget], title: str, text: str, action: str,
            destructive: bool = False, detail: str = "") -> bool:
    """Ask a yes/no question whose buttons say what happens.

    Returns True only when the user picks `action`. Cancel is the default for
    destructive actions so a stray Enter cannot delete anything.
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    yes = box.addButton(action, QMessageBox.ButtonRole.AcceptRole)
    no = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(no if destructive else yes)
    box.setEscapeButton(no)
    box.exec()
    return box.clickedButton() is yes


# ---------------------------------------------------------------------------
# Formatting (Harbor "Words": $1,240.00, +$412.50, −$88.00)
# ---------------------------------------------------------------------------

def fmt_money(value: Optional[float], decimals: int = 2, dash: str = "—") -> str:
    """$1,234.56, with a real minus sign for negatives; `dash` for None."""
    if value is None:
        return dash
    v = float(value)
    sign = MINUS if v < 0 and round(abs(v), decimals) != 0 else ""
    return f"{sign}${abs(v):,.{decimals}f}"


def fmt_signed_money(value: Optional[float], decimals: int = 2, dash: str = "—") -> str:
    """+$412.50 / −$88.00 / $0.00 — gains are never shown by colour alone."""
    if value is None:
        return dash
    v = float(value)
    if round(v, decimals) > 0:
        return f"+${v:,.{decimals}f}"
    return fmt_money(v, decimals, dash)


def fmt_int(value: Optional[int], dash: str = "—") -> str:
    return dash if value is None else f"{int(value):,d}"


_STATUS_LABELS: Dict[str, str] = {
    "WAITING": "Pending", "OPEN": "Open", "CLOSED": "Closed",
    "SHORT": "Short", "COVERED": "Covered",
}


def fmt_status(status: str) -> str:
    """Sentence-case label for a Trade.status code (codes stay upper-case)."""
    return _STATUS_LABELS.get(status, (status or "").capitalize())
